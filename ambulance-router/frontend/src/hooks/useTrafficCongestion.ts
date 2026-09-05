import { useCallback, useEffect, useRef, useState } from "react";
import { fetchTrafficCongestion, seedTraffic } from "../api/client";
import type { TrafficCongestionResponse } from "../types";

export function useTrafficCongestion(pollIntervalMs = 10000) {
  const [congestion, setCongestion] = useState<TrafficCongestionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isFetchingRef = useRef(false);

  const loadTraffic = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    try {
      const data = await fetchTrafficCongestion();
      setCongestion(data);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load traffic congestion";
      setError(msg);
    } finally {
      setLoading(false);
      isFetchingRef.current = false;
    }
  }, []);

  const triggerReseed = useCallback(async () => {
    setLoading(true);
    try {
      const data = await seedTraffic();
      setCongestion(data);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to re-seed traffic";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTraffic();
    const timer = setInterval(loadTraffic, pollIntervalMs);
    return () => clearInterval(timer);
  }, [loadTraffic, pollIntervalMs]);

  return {
    congestion,
    loading,
    error,
    refresh: loadTraffic,
    reseed: triggerReseed,
  };
}
