import { useCallback, useEffect, useState } from "react";
import { api, describeError } from "../api/client";
import type { HealthResponse, InfoResponse } from "../api/types";
import { useSettings } from "../state/settings";
import type { UiError } from "../components/ErrorBanner";

export interface HealthState {
  status: "checking" | "ok" | "down";
  data?: HealthResponse;
  error?: UiError;
  checkedAt?: number;
}

const POLL_MS = 10_000;

/** Polls GET /health. Keeps the last good payload while the API is down. */
export function useHealth(): HealthState & { refresh: () => void } {
  const { keyVersion } = useSettings();
  const [state, setState] = useState<HealthState>({ status: "checking" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    let timer: number | undefined;
    const run = async () => {
      try {
        const data = await api.health(ctl.signal);
        setState({ status: "ok", data, checkedAt: Date.now() });
      } catch (e) {
        if (ctl.signal.aborted) return;
        setState((prev) => ({ status: "down", data: prev.data, error: describeError(e), checkedAt: Date.now() }));
      }
      if (!ctl.signal.aborted) timer = window.setTimeout(run, POLL_MS);
    };
    void run();
    return () => {
      ctl.abort();
      window.clearTimeout(timer);
    };
  }, [keyVersion, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, refresh };
}

export interface InfoState {
  data?: InfoResponse;
  error?: UiError;
  loading: boolean;
}

/** Runtime info (models, providers). Refetched when the API key changes or the API comes back. */
export function useInfo(apiUp: boolean): InfoState {
  const { keyVersion } = useSettings();
  const [state, setState] = useState<InfoState>({ loading: true });

  useEffect(() => {
    const ctl = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    api
      .info(ctl.signal)
      .then((data) => setState({ data, loading: false }))
      .catch((e) => {
        if (!ctl.signal.aborted) setState((s) => ({ data: s.data, error: describeError(e), loading: false }));
      });
    return () => ctl.abort();
  }, [keyVersion, apiUp]);

  return state;
}
