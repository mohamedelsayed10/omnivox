import { useCallback, useEffect, useRef, useState } from "react";
import { inspectorStore, type Origin } from "../inspector/store";
import type { TranscriptEntry } from "../state/voiceTypes";

/**
 * Builds the user's side of the transcript from `stt.interim` / `stt.final`
 * trace events of the given origin. Interim text revises one entry in place;
 * the final event commits it.
 */
export function useTraceTranscript(origin: Origin, run: number | null) {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  /** True once any stt event arrived for this run (so streams need not double-render the user). */
  const sawStt = useRef(false);
  const [saw, setSaw] = useState(false);

  useEffect(() => {
    if (run == null) return;
    return inspectorStore.onEvent((e) => {
      if (e.origin !== origin || e.run !== run || e.source !== "stt") return;
      const text = typeof e.data.text === "string" ? e.data.text : "";
      if (e.type !== "interim" && e.type !== "final") return;
      if (!sawStt.current) {
        sawStt.current = true;
        setSaw(true);
      }
      const id = `u:${run}:${e.turn}`;
      const final = e.type === "final";
      setEntries((list) => {
        const i = list.findIndex((x) => x.id === id);
        if (i === -1) return [...list, { id, role: "user", text, final, ts: e.ts }];
        const prev = list[i] as TranscriptEntry;
        if (prev.final && !final) return list; // late interim after the final: ignore
        const next = list.slice();
        next[i] = { ...prev, text, final };
        return next;
      });
    });
  }, [origin, run]);

  const reset = useCallback(() => {
    sawStt.current = false;
    setSaw(false);
    setEntries([]);
  }, []);

  return { entries, sawStt: saw, reset };
}
