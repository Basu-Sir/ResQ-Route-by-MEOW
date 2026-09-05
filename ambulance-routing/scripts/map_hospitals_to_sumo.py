import json
import random
import math
from pathlib import Path

import sumolib


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Actual SUMO network
SUMO_NET_FILE = BASE_DIR / "net.net.xml"

# OSM hospital data produced by your extract script
# Change this ONLY if your extracted file has a different name.
INPUT_HOSPITALS_FILE = BASE_DIR / "data" / "hospitals_raw.json"

# Final file used by the backend
OUTPUT_HOSPITALS_FILE = BASE_DIR / "data" / "hospitals.json"

# Temporary/demo ICU bed range
MIN_ICU_BEDS = 0
MAX_ICU_BEDS = 10

# Keep random values reproducible for now.
# Remove/change this later when you want different values.
random.seed(42)


# ============================================================
# LOAD SUMO NETWORK
# ============================================================

def load_sumo_network():
    print(f"Loading SUMO network from: {SUMO_NET_FILE}")

    if not SUMO_NET_FILE.exists():
        raise FileNotFoundError(
            f"SUMO network not found:\n{SUMO_NET_FILE}"
        )

    net = sumolib.net.readNet(str(SUMO_NET_FILE))

    print(f"SUMO network loaded.")
    print(f"Nodes: {len(net.getNodes())}")
    print(f"Edges: {len(net.getEdges())}")

    return net


# ============================================================
# LOAD HOSPITAL DATA
# ============================================================

def load_hospitals():
    print(f"\nLoading hospitals from: {INPUT_HOSPITALS_FILE}")

    if not INPUT_HOSPITALS_FILE.exists():
        raise FileNotFoundError(
            f"Hospital file not found:\n{INPUT_HOSPITALS_FILE}"
        )

    with open(INPUT_HOSPITALS_FILE, "r", encoding="utf-8") as f:
        hospitals = json.load(f)

    if not isinstance(hospitals, list):
        raise ValueError(
            "Expected hospitals.json to contain a JSON array."
        )

    print(f"Loaded {len(hospitals)} hospitals.")

    return hospitals


# ============================================================
# FIND NEAREST SUMO NODE
# ============================================================

def build_node_coordinates(net):
    """
    Convert all SUMO nodes into a list of:
        (node_id, x, y)
    """

    nodes = []

    for node in net.getNodes():
        node_id = node.getID()
        x, y = node.getCoord()

        nodes.append(
            (
                node_id,
                float(x),
                float(y)
            )
        )

    return nodes


def nearest_sumo_node(net, nodes, latitude, longitude):
    """
    Convert WGS84 latitude/longitude to SUMO network coordinates,
    then find the nearest SUMO node.
    """

    # SUMO expects longitude first, latitude second.
    x, y = net.convertLonLat2XY(
        float(longitude),
        float(latitude)
    )

    best_node_id = None
    best_distance = math.inf

    for node_id, node_x, node_y in nodes:

        distance_squared = (
            (node_x - x) ** 2
            + (node_y - y) ** 2
        )

        if distance_squared < best_distance:
            best_distance = distance_squared
            best_node_id = node_id

    if best_node_id is None:
        raise RuntimeError(
            "Could not find a SUMO node."
        )

    return best_node_id


# ============================================================
# NORMALIZE HOSPITAL DATA
# ============================================================

def process_hospitals(hospitals, net):
    """
    Add SUMO node IDs and temporary random ICU bed counts.
    """

    print("\nBuilding SUMO node index...")

    nodes = build_node_coordinates(net)

    print(f"Indexed {len(nodes)} SUMO nodes.")

    processed = []

    mapped_count = 0
    skipped_count = 0

    print("\nMapping hospitals to SUMO nodes...")

    for i, hospital in enumerate(hospitals, start=1):

        try:
            latitude = float(hospital["latitude"])
            longitude = float(hospital["longitude"])

        except (KeyError, TypeError, ValueError):

            print(
                f"Skipping hospital #{i}: "
                "missing/invalid latitude or longitude"
            )

            skipped_count += 1
            continue

        # ----------------------------------------------------
        # Hospital ID
        # ----------------------------------------------------

        hospital_id = hospital.get("id")

        if not hospital_id:
            hospital_id = f"hospital_{i}"

        # ----------------------------------------------------
        # Hospital name
        # ----------------------------------------------------

        name = hospital.get("name")

        if not name:
            name = "Unnamed Hospital"

        # ----------------------------------------------------
        # Find nearest SUMO node
        # ----------------------------------------------------

        try:

            sumo_node_id = nearest_sumo_node(
                net,
                nodes,
                latitude,
                longitude
            )

        except Exception as e:

            print(
                f"Could not map hospital {hospital_id}: {e}"
            )

            skipped_count += 1
            continue

        # ----------------------------------------------------
        # Random ICU beds
        # ----------------------------------------------------

        icu_beds = random.randint(
            MIN_ICU_BEDS,
            MAX_ICU_BEDS
        )

        # ----------------------------------------------------
        # Create final hospital object
        # ----------------------------------------------------

        mapped_hospital = {
            "id": str(hospital_id),
            "name": str(name),
            "latitude": latitude,
            "longitude": longitude,
            "sumo_node_id": str(sumo_node_id),
            "icu_beds": icu_beds
        }

        processed.append(mapped_hospital)

        mapped_count += 1

        # Print progress every 50 hospitals
        if mapped_count % 50 == 0:
            print(
                f"Mapped {mapped_count}/{len(hospitals)} hospitals..."
            )

    print("\n--------------------------------")
    print("Mapping complete")
    print("--------------------------------")
    print(f"Input hospitals : {len(hospitals)}")
    print(f"Mapped hospitals: {mapped_count}")
    print(f"Skipped hospitals: {skipped_count}")

    return processed


# ============================================================
# SAVE OUTPUT
# ============================================================

def save_hospitals(hospitals):
    """
    Save mapped hospitals to data/hospitals.json
    """

    OUTPUT_HOSPITALS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_HOSPITALS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            hospitals,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(
        f"\nSaved {len(hospitals)} hospitals to:"
    )
    print(OUTPUT_HOSPITALS_FILE)


# ============================================================
# MAIN
# ============================================================

def main():

    print("============================================")
    print(" Mumbai Hospital → SUMO Node Mapper")
    print("============================================")

    # 1. Load SUMO network
    net = load_sumo_network()

    # 2. Load actual OSM hospital data
    hospitals = load_hospitals()

    # 3. Map hospitals + generate ICU beds
    processed_hospitals = process_hospitals(
        hospitals,
        net
    )

    # 4. Save final data
    save_hospitals(
        processed_hospitals
    )

    print("\n============================================")
    print("DONE")
    print("============================================")

    if processed_hospitals:

        print("\nExample hospital:")

        print(
            json.dumps(
                processed_hospitals[0],
                indent=2,
                ensure_ascii=False
            )
        )


if __name__ == "__main__":
    main()