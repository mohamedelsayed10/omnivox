/**
 * DEV ONLY. Replays a scripted call from the mock server (`GET /__mock/trace`)
 * through the exact code path real data-channel events take, and fakes the
 * agent state, transcript and audio levels from those events. It exists so the
 * Voice view and Inspector can be exercised without LiveKit or a backend.
 * App.tsx only mounts this when `import.meta.env.DEV` is true, so it is
 * tree-shaken out of production builds.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTraceTranscript } from "../hooks/useTraceTranscript";
import { inspectorStore } from "../inspector/store";
import type { UiError } from "../components/ErrorBanner";
import type { TranscriptEntry, VoiceSession, VoiceState } from "../state/voiceTypes";
import { DemoContext, type DemoApi } from "./demoContext";

export function DemoProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [state, setState] = useState<VoiceState>("disconnected");
  const [micEnabled, setMicEnabled] = useState(true);
  const [error, setError] = useState<UiError | null>(null);
  const [agentLines, setAgentLines] = useState<TranscriptEntry[]>([]);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const trace = useTraceTranscript("demo", runId);

  const source = useRef<EventSource | null>(null);
  const runRef = useRef<number | null>(null);
  const userSpeaking = useRef(false);
  const agentState = useRef<VoiceState>("disconnected");
  const lastAgentFinal = useRef(true);
  const agentId = useRef("");
  const lines = useRef(0);
  const micLevel = useRef(0);
  const agentLevel = useRef(0);

  // Synthetic audio levels so the orb reacts to the replayed states.
  useEffect(() => {
    if (!active) {
      micLevel.current = 0;
      agentLevel.current = 0;
      return;
    }
    let raf = 0;
    const loop = (t: number) => {
      const wobble = 0.5 + 0.5 * Math.sin(t / 90) * Math.sin(t / 230 + 1.3);
      micLevel.current = userSpeaking.current && micEnabled ? 0.1 + 0.3 * wobble : 0.012;
      agentLevel.current = agentState.current === "speaking" ? 0.14 + 0.34 * wobble : 0;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [active, micEnabled]);

  // Derive the visible state from replayed events.
  useEffect(
    () =>
      inspectorStore.onEvent((e) => {
        if (e.origin !== "demo" || e.run !== runRef.current) return;
        if (e.source === "vad" && e.type === "user_state") {
          userSpeaking.current = e.data.state === "speaking";
          if (userSpeaking.current) {
            agentState.current = "listening";
            setState("listening");
          }
        } else if (e.source === "session" && e.type === "agent_state") {
          const s = e.data.state;
          if (s === "initializing" || s === "idle" || s === "listening" || s === "thinking" || s === "speaking") {
            agentState.current = s;
            setState(s);
          }
        }
      }),
    [],
  );

  const stop = useCallback(() => {
    source.current?.close();
    source.current = null;
    userSpeaking.current = false;
    agentState.current = "disconnected";
    setActive(false);
    setStarting(false);
    setState("disconnected");
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(() => {
    if (source.current) return;
    setError(null);
    setStarting(true);
    setAgentLines([]);
    setHidden(new Set());
    lastAgentFinal.current = true;
    lines.current = 0;
    trace.reset();

    const speed = Number(new URLSearchParams(window.location.search).get("speed")) || 1;
    const run = inspectorStore.beginRun("demo", "Sample call (replayed)");
    runRef.current = run;
    setRunId(run);

    const es = new EventSource(`/__mock/trace?speed=${speed}`);
    source.current = es;
    let finished = false;
    es.onopen = () => {
      setStarting(false);
      setActive(true);
      agentState.current = "initializing";
      setState("initializing");
    };
    es.addEventListener("trace", (ev) => {
      inspectorStore.ingestRaw((ev as MessageEvent<string>).data, run, "demo");
    });
    es.addEventListener("transcript", (ev) => {
      try {
        const f = JSON.parse((ev as MessageEvent<string>).data) as { role: "agent"; text: string; final: boolean };
        // Decide the entry id outside the state updater (updaters must stay pure: StrictMode runs them twice).
        if (lastAgentFinal.current) agentId.current = `a:${run}:${++lines.current}`;
        lastAgentFinal.current = f.final;
        const id = agentId.current;
        setAgentLines((list) => {
          const i = list.findIndex((x) => x.id === id);
          if (i === -1) return [...list, { id, role: "agent", text: f.text, final: f.final, ts: Date.now() }];
          const next = list.slice();
          next[i] = { ...(next[i] as TranscriptEntry), text: f.text, final: f.final };
          return next;
        });
      } catch {
        /* ignore malformed demo frame */
      }
    });
    es.addEventListener("done", () => {
      finished = true;
      es.close();
      source.current = null;
      agentState.current = "listening";
      setState("listening");
    });
    es.onerror = () => {
      if (finished) return;
      // Never opened, or the stream broke: stop instead of letting EventSource reconnect and replay.
      es.close();
      source.current = null;
      setStarting(false);
      setActive(false);
      setState("disconnected");
      setError({
        message: "Could not reach the dev mock (GET /__mock/trace). Start it with `npm run dev:mock`.",
        code: "demo_unavailable",
      });
    };
  }, [trace]);

  // Dev convenience: /?demo starts the replay on load (used for scripted screenshots).
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("demo")) start();
  }, [start]);

  const transcript = useMemo(
    () => [...trace.entries, ...agentLines].filter((e) => !hidden.has(e.id)).sort((a, b) => a.ts - b.ts),
    [trace.entries, agentLines, hidden],
  );

  const session = useMemo<VoiceSession>(
    () => ({
      mode: "demo",
      state,
      connected: active,
      connecting: starting,
      micEnabled,
      error,
      warning: null,
      connect: async () => start(),
      disconnect: () => stop(),
      toggleMic: () => setMicEnabled((v) => !v),
      transcript,
      clearTranscript: () => setHidden(new Set(transcript.map((e) => e.id))),
      levels: { mic: micLevel, agent: agentLevel },
      devices: { list: [{ id: "demo", label: "Demo microphone (simulated)" }], activeId: "demo", select: () => undefined },
      roomName: "sample-call",
    }),
    [state, active, starting, micEnabled, error, start, stop, transcript],
  );

  const api = useMemo<DemoApi>(() => ({ active, starting, start, stop, session }), [active, starting, start, stop, session]);

  return <DemoContext.Provider value={api}>{children}</DemoContext.Provider>;
}
