import { useEffect, useRef, useState, useCallback } from "react";
import { fetchAmbulances, fetchFleetSummary } from "../api/client";
import type { AmbulanceState, FleetSummary } from "../types";

export function useAmbulances(pollIntervalMs = 1500) {
  const [ambulances, setAmbulances] = useState<AmbulanceState[]>([]);
  const [summary, setSummary] = useState<FleetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isFetchingRef = useRef(false);

  const loadAmbulances = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    try {
      const [ambData, sumData] = await Promise.all([
        fetchAmbulances(),
        fetchFleetSummary().catch(() => null),
      ]);
      setAmbulances(ambData);
      if (sumData) {
        setSummary(sumData);
      } else {
        const total = ambData.length;
        const roaming = ambData.filter((a) => a.is_roaming).length;
        const standby = ambData.filter((a) => !a.is_roaming && a.status === "AVAILABLE").length;
        const available = ambData.filter((a) => a.status === "AVAILABLE").length;
        const dispatched = ambData.filter((a) => a.status === "DISPATCHED").length;
        const with_patient = ambData.filter((a) => a.has_patient).length;
        setSummary({ total, roaming, standby, available, dispatched, with_patient });
      }
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load ambulances";
      setError(msg);
    } finally {
      setLoading(false);
      isFetchingRef.current = false;
    }
  }, []);

  useEffect(() => {
    loadAmbulances();
    const timer = setInterval(loadAmbulances, pollIntervalMs);
    return () => clearInterval(timer);
  }, [loadAmbulances, pollIntervalMs]);

  return { ambulances, summary, loading, error, refresh: loadAmbulances };
}

