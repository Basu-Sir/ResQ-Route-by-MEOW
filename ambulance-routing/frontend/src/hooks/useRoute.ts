import { useCallback, useState } from "react";
import { calculateRoute, ApiError } from "../api/client";
import type { RouteRequest, RouteResponse } from "../types";

interface UseRouteResult {
  route: RouteResponse | null;
  loading: boolean;
  error: string | null;
  dispatch: (req: RouteRequest) => Promise<void>;
  reset: () => void;
}

/**
 * Wraps POST /route. All pathfinding happens on the backend (rustworkx over
 * the SUMO graph) — this hook only manages request lifecycle state.
 */
export function useRoute(): UseRouteResult {
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dispatch = useCallback(async (req: RouteRequest) => {
    setLoading(true);
    setError(null);
    try {
      const result = await calculateRoute(req);
      setRoute(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Could not reach the routing service.";
      setError(message);
      setRoute(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setRoute(null);
    setError(null);
  }, []);

  return { route, loading, error, dispatch, reset };
}
