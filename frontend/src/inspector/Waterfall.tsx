import type { TurnSummary } from "../api/types";
import { formatMs } from "../lib/format";

interface Stage {
  key: keyof Omit<TurnSummary, "total_ms">;
  label: string;
  short: string;
  cls: string;
}

/** speech end → end-of-turn → LLM first token → TTS first audio */
const STAGES: Stage[] = [
  { key: "eot_ms", label: "Speech end → end-of-turn", short: "End of turn", cls: "st-eot" },
  { key: "llm_ttft_ms", label: "End-of-turn → LLM first token", short: "LLM first token", cls: "st-llm" },
  { key: "tts_ttfb_ms", label: "LLM → TTS first audio", short: "TTS first audio", cls: "st-tts" },
];

/**
 * Sequential latency waterfall for one turn, built from `latency.turn_summary`.
 * Stages the summary does not carry (e.g. text chat has no end-of-turn or TTS)
 * are simply omitted. `scaleMax` lets several turns share one time axis.
 */
export function Waterfall({
  summary,
  scaleMax,
  compact = false,
}: {
  summary: Partial<TurnSummary>;
  scaleMax?: number;
  compact?: boolean;
}) {
  let cursor = 0;
  const rows = STAGES.flatMap((s) => {
    const v = summary[s.key];
    if (v == null || !Number.isFinite(v)) return [];
    const row = { ...s, start: cursor, dur: Math.max(0, v) };
    cursor += row.dur;
    return [row];
  });
  const total = summary.total_ms != null && Number.isFinite(summary.total_ms) ? summary.total_ms : cursor;
  const scale = Math.max(scaleMax ?? 0, total, cursor, 1);
  const pct = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;

  if (!rows.length && !total) return <p className="muted-note">No latency stages in this summary.</p>;

  const description = `${rows.map((r) => `${r.short} ${formatMs(r.dur)}`).join(", ")}; total ${formatMs(total)}`;

  return (
    <div className={`wf${compact ? " compact" : ""}`} role="img" aria-label={`Latency waterfall: ${description}`}>
      <div className="wf-axis" aria-hidden>
        <span>speech end</span>
        <span>{formatMs(scale)}</span>
      </div>
      {rows.map((r) => (
        <div className="wf-row" key={r.key} aria-hidden>
          <div className="wf-label" title={r.label}>
            {r.short}
          </div>
          <div className="wf-track">
            <div className={`wf-bar ${r.cls}`} style={{ left: pct(r.start), width: `max(3px, ${pct(r.dur)})` }} />
          </div>
          <div className="wf-val mono">{formatMs(r.dur)}</div>
        </div>
      ))}
      <div className="wf-row total" aria-hidden>
        <div className="wf-label">Total</div>
        <div className="wf-track">
          <div className="wf-bar st-total" style={{ left: 0, width: pct(total) }} />
        </div>
        <div className="wf-val mono">{formatMs(total)}</div>
      </div>
    </div>
  );
}
