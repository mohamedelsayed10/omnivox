import { useEffect, useLayoutEffect, useRef, type MutableRefObject } from "react";
import { AudioLines, FlaskConical, Loader2, Mic, MicOff, PhoneOff, Trash2 } from "lucide-react";
import { ErrorBanner } from "../components/ErrorBanner";
import { Orb } from "../components/Orb";
import { useDemo } from "../dev/demoContext";
import { usePrefersReducedMotion } from "../hooks/useMediaQuery";
import { useSettings } from "../state/settings";
import { useVoiceSession } from "../state/voice";
import type { VoiceState } from "../state/voiceTypes";

const COPY: Record<VoiceState, { title: string; hint: string }> = {
  disconnected: { title: "Ready when you are", hint: "Start a conversation and just talk. The Inspector shows every step." },
  connecting: { title: "Connecting…", hint: "Getting a token and joining the room." },
  initializing: { title: "Waking the agent…", hint: "Waiting for the agent worker to join the room." },
  idle: { title: "Idle", hint: "Connected. The agent is waiting." },
  listening: { title: "Listening", hint: "Speak naturally. The agent decides when you have finished." },
  thinking: { title: "Thinking", hint: "Routing through the agent graph." },
  speaking: { title: "Speaking", hint: "You can interrupt by talking." },
  failed: { title: "The agent failed to start", hint: "Check the agent worker logs, then try again." },
};

export function VoiceView() {
  const s = useVoiceSession();
  const demo = useDemo();
  const { theme } = useSettings();
  const reduced = usePrefersReducedMotion();
  const copy = COPY[s.state];

  return (
    <section className="view voice" aria-label="Voice assistant">
      <div className={`stage card state-${s.state}`}>
        <div className="stage-orb">
          <Orb state={s.state} mic={s.levels.mic} agent={s.levels.agent} theme={theme} reducedMotion={reduced} />
        </div>

        <div className="stage-text" role="status" aria-live="polite">
          <span className="state-pill">
            <i aria-hidden />
            {s.mode === "demo" ? "Simulated · " : ""}
            {s.state}
          </span>
          <h2>{copy.title}</h2>
          <p>{copy.hint}</p>
        </div>

        <div className="controls">
          <button
            className={`btn btn-icon round${s.micEnabled ? "" : " muted-mic"}`}
            onClick={s.toggleMic}
            disabled={!s.connected}
            aria-pressed={!s.micEnabled}
            aria-label={s.micEnabled ? "Mute microphone" : "Unmute microphone"}
            title={s.micEnabled ? "Mute microphone" : "Unmute microphone"}
          >
            {s.micEnabled ? <Mic size={20} /> : <MicOff size={20} />}
          </button>

          {s.connected ? (
            <button className="btn btn-danger call-btn" onClick={() => void s.disconnect()}>
              <PhoneOff size={18} /> End call
            </button>
          ) : (
            <button className="btn btn-primary call-btn" onClick={() => void s.connect()} disabled={s.connecting}>
              {s.connecting ? <Loader2 size={18} className="spin" /> : <AudioLines size={18} />}
              {s.connecting ? "Connecting…" : "Start conversation"}
            </button>
          )}

          <div className="device">
            <LevelMeter level={s.levels.mic} active={s.connected && s.micEnabled} />
            <label className="sr-only" htmlFor="mic-device">
              Microphone
            </label>
            <select
              id="mic-device"
              className="select"
              value={s.devices.activeId}
              onChange={(e) => s.devices.select(e.target.value)}
              disabled={s.devices.list.length === 0}
            >
              {s.devices.list.length === 0 && <option value="">Default microphone</option>}
              {s.devices.list.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          {demo && !s.connected && (
            <button
              className="btn btn-ghost btn-sm dev-only"
              onClick={demo.start}
              disabled={demo.starting}
              title="Dev only: replay a scripted call from the mock server (no LiveKit needed)"
            >
              <FlaskConical size={15} /> Simulate call
            </button>
          )}
        </div>
      </div>

      {s.error && (
        <ErrorBanner
          error={s.error}
          title={s.connected ? undefined : "Could not start the call"}
          onRetry={s.connected || s.connecting ? undefined : () => void s.connect()}
        />
      )}
      {s.warning && <ErrorBanner tone="warn" error={{ message: s.warning }} />}

      <Transcript />
    </section>
  );
}

// ------------------------------------------------------------------ transcript

function Transcript() {
  const s = useVoiceSession();
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [s.transcript]);

  return (
    <div className="transcript card">
      <div className="tx-head">
        <h2>Live transcript</h2>
        <span className="muted">{s.transcript.length ? `${s.transcript.length} messages` : "waiting for speech"}</span>
        <button
          className="btn btn-ghost btn-sm"
          style={{ marginLeft: "auto" }}
          onClick={s.clearTranscript}
          disabled={s.transcript.length === 0}
        >
          <Trash2 size={14} /> Clear
        </button>
      </div>
      <div
        className="tx-list"
        ref={ref}
        role="log"
        aria-live="polite"
        aria-label="Conversation transcript"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        {s.transcript.length === 0 ? (
          <div className="empty">
            <Mic size={26} aria-hidden />
            <strong>Nothing said yet</strong>
            <span>Interim words appear as you speak and settle when the turn ends; the agent’s reply streams in beside them.</span>
          </div>
        ) : (
          s.transcript.map((e) => (
            <div key={e.id} className={`tx ${e.role}${e.final ? "" : " interim"}`}>
              <span className="who">{e.role === "user" ? "You" : "OmniVox"}</span>
              <p>
                {e.text}
                {!e.final && <span className="caret" aria-hidden />}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ mic meter

const BARS = 12;

/** Tiny equaliser driven straight from a level ref (no React renders). */
function LevelMeter({ level, active }: { level: MutableRefObject<number>; active: boolean }) {
  const wrap = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const bars = Array.from(wrap.current?.children ?? []) as HTMLElement[];
    let raf = 0;
    const loop = (t: number) => {
      const l = active ? Math.min(1, Math.pow(level.current * 2.6, 0.6)) : 0;
      bars.forEach((b, i) => {
        const jitter = 0.55 + 0.45 * Math.sin(t / 130 + i * 1.7);
        const h = Math.max(0.12, l * jitter * (1 - Math.abs(i - BARS / 2) / BARS) * 1.6);
        b.style.transform = `scaleY(${Math.min(1, h)})`;
      });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [level, active]);

  return (
    <span className="meter" ref={wrap} aria-hidden>
      {Array.from({ length: BARS }, (_, i) => (
        <i key={i} />
      ))}
    </span>
  );
}
