import { useEffect, useState } from "react";
import { fetchHospitals } from "../api/client";
import type { HospitalListItem } from "../types";

interface UseHospitalsResult {
  hospitals: HospitalListItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Loads the ~930-hospital list once on mount. This is the ONLY hospital
 * data the browser ever receives — no SUMO node IDs, no graph data.
 */
export function useHospitals(): UseHospitalsResult {
  const [hospitals, setHospitals] = useState<HospitalListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await fetchHospitals();
      setHospitals(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load hospitals");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    fetchHospitals()
      .then((data) => {
        if (!cancelled) setHospitals(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message ?? "Failed to load hospitals");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { hospitals, loading, error, refresh };
}
