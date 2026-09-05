#!/usr/bin/env python3
"""
extract_hospitals.py

Streams a (nodes-before-ways-before-relations) OSM XML file and extracts
real hospital locations tagged amenity=hospital or healthcare=hospital.

Handles hospitals represented as:
  - <node>                (direct point with lat/lon)
  - <way>                 (centroid of its member node coordinates)
  - <relation>            (centroid of member ways' node coordinates,
                            typically multipolygon hospital grounds)

Outputs hospitals.json as a list of:
  {"id": "...", "name": "...", "latitude": 0.0, "longitude": 0.0}

Only includes data actually present in the OSM file. No invented fields
(no ICU beds, no addresses, etc.). "name" is null if OSM has no name tag.

Usage:
    python extract_hospitals.py fixed.osm hospitals.json
"""

import sys
import json
import xml.etree.ElementTree as ET


def is_hospital(tags: dict) -> bool:
    return tags.get("amenity") == "hospital" or tags.get("healthcare") == "hospital"


def centroid(coords):
    """Simple average centroid of a list of (lat, lon) tuples."""
    if not coords:
        return None
    lat = sum(c[0] for c in coords) / len(coords)
    lon = sum(c[1] for c in coords) / len(coords)
    return lat, lon


def extract_hospitals(osm_path: str):
    """
    Two-pass streaming parse. This makes the script robust regardless of
    whether the OSM file has nodes before ways/relations or not (Overpass
    exports can come out in either order depending on the query used).

    Pass 1: stream through once, collecting ALL node coordinates and ALL
            way node-ref lists into memory (fine for city-sized extracts).
    Pass 2: stream through again, this time actually extracting hospitals,
            using the fully-populated lookups from pass 1 to compute
            centroids for ways/relations.
    """
    hospitals = []

    # Coordinates for every node, needed to compute way/relation centroids.
    node_coords = {}

    # Node-id lists for every way, needed to resolve relation members
    # that reference ways (e.g. multipolygon hospital grounds).
    way_nodes = {}

    # ---- Pass 1: collect all node coords + way node-ref lists ----
    current = None
    for event, elem in ET.iterparse(osm_path, events=("start", "end")):
        tag = elem.tag
        if event == "start":
            if tag == "node":
                current = {"id": elem.get("id"), "lat": elem.get("lat"), "lon": elem.get("lon")}
            elif tag == "way":
                current = {"id": elem.get("id"), "nds": []}
            elif tag == "nd" and current is not None and "nds" in current:
                current["nds"].append(elem.get("ref"))
        elif event == "end":
            if tag == "node" and current is not None:
                try:
                    node_coords[current["id"]] = (float(current["lat"]), float(current["lon"]))
                except (TypeError, ValueError):
                    pass
                current = None
                elem.clear()
            elif tag == "way" and current is not None:
                way_nodes[current["id"]] = current["nds"]
                current = None
                elem.clear()
            elif tag == "relation":
                elem.clear()

    # ---- Pass 2: extract hospitals using the complete lookups above ----
    current = None
    context = ET.iterparse(osm_path, events=("start", "end"))

    for event, elem in context:
        tag = elem.tag

        if event == "start":
            if tag == "node":
                current = {
                    "type": "node",
                    "id": elem.get("id"),
                    "lat": elem.get("lat"),
                    "lon": elem.get("lon"),
                    "tags": {},
                }
            elif tag == "way":
                current = {
                    "type": "way",
                    "id": elem.get("id"),
                    "nds": [],
                    "tags": {},
                }
            elif tag == "relation":
                current = {
                    "type": "relation",
                    "id": elem.get("id"),
                    "members": [],  # list of (type, ref)
                    "tags": {},
                }
            elif tag == "tag" and current is not None:
                current["tags"][elem.get("k")] = elem.get("v")
            elif tag == "nd" and current is not None and current["type"] == "way":
                current["nds"].append(elem.get("ref"))
            elif tag == "member" and current is not None and current["type"] == "relation":
                current["members"].append((elem.get("type"), elem.get("ref")))

        elif event == "end":
            if tag == "node" and current is not None:
                nid = current["id"]
                try:
                    lat = float(current["lat"])
                    lon = float(current["lon"])
                    node_coords[nid] = (lat, lon)
                except (TypeError, ValueError):
                    lat = lon = None

                if is_hospital(current["tags"]) and lat is not None and lon is not None:
                    hospitals.append({
                        "id": f"node/{nid}",
                        "name": current["tags"].get("name"),
                        "latitude": lat,
                        "longitude": lon,
                    })
                current = None
                elem.clear()

            elif tag == "way" and current is not None:
                wid = current["id"]
                nds = current["nds"]
                way_nodes[wid] = nds  # keep for potential relation lookups

                if is_hospital(current["tags"]):
                    coords = [node_coords[n] for n in nds if n in node_coords]
                    c = centroid(coords)
                    if c is not None:
                        hospitals.append({
                            "id": f"way/{wid}",
                            "name": current["tags"].get("name"),
                            "latitude": c[0],
                            "longitude": c[1],
                        })
                current = None
                elem.clear()

            elif tag == "relation" and current is not None:
                rid = current["id"]
                if is_hospital(current["tags"]):
                    coords = []
                    for mtype, mref in current["members"]:
                        if mtype == "way" and mref in way_nodes:
                            coords.extend(
                                node_coords[n] for n in way_nodes[mref] if n in node_coords
                            )
                        elif mtype == "node" and mref in node_coords:
                            coords.append(node_coords[mref])
                    c = centroid(coords)
                    if c is not None:
                        hospitals.append({
                            "id": f"relation/{rid}",
                            "name": current["tags"].get("name"),
                            "latitude": c[0],
                            "longitude": c[1],
                        })
                current = None
                elem.clear()

    return hospitals


def main():
    if len(sys.argv) != 3:
        print("Usage: python extract_hospitals.py <input.osm> <output.json>")
        sys.exit(1)

    osm_path = sys.argv[1]
    out_path = sys.argv[2]

    hospitals = extract_hospitals(osm_path)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(hospitals, f, ensure_ascii=False, indent=2)

    named = sum(1 for h in hospitals if h["name"])
    print(f"Extracted {len(hospitals)} hospital(s) -> {out_path}")
    print(f"  {named} with a name tag, {len(hospitals) - named} unnamed")


if __name__ == "__main__":
    main()