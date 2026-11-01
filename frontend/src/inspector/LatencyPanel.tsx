import { Gauge } from "lucide-react";
import { formatMs } from "../lib/format";
import type { TurnGroup } from "./store";
import { Waterfall } from "./Waterfall";

function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return NaN;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[i] as number;
}

/** Latency across turns on one shared time axis, with a small summary. */
export function LatencyPanel({ groups }: { groups: TurnGroup[] }) {
  const withSummary = groups.filter((g) => g.summary && g.summary.total_ms != null);
  if (!withSummary.length) {
    return (
      <div className="empty">
        <Gauge size={28} aria-hidden />
        <strong>No latency data yet</strong>
        <span>Each completed turn emits a latency summary: end-of-turn, LLM first token and TTS first audio.</span>
      </div>
    );
  }
  const totals = withSummary.map((g) => g.summary!.total_ms as number).sort((a, b) => a - b);
  const avg = totals.reduce((a, b) => a + b, 0) / totals.length;
  const scaleMax = Math.max(...totals);
  const last = withSummary[withSummary.length - 1]!;

  return (
    <div className="latency">
      <div className="stats">
        <Stat label="Last" value={formatMs(last.summary!.total_ms)} />
        <Stat label="Average" value={formatMs(avg)} />
        <Stat label="Median" value={formatMs(percentile(totals, 50))} />
        <Stat label="Slowest" value={formatMs(scaleMax)} />
      </div>
      <Legend />
      <ol className="lat-list">
        {withSummary.map((g) => (
          <li key={g.key} className="lat-item">
            <div className="lat-head">
              <strong>{g.turn === 0 ? "Session" : `Turn ${g.turn}`}</strong>
              <span className="lat-run">{g.runLabel}</span>
              {g.userText && <span className="lat-text">“{g.userText}”</span>}
            </div>
            <Waterfall summary={g.summary!} scaleMax={scaleMax} compact />
          </li>
        ))}
      </ol>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value mono">{value}</span>
    </div>
  );
}

function Legend() {
  return (
    <ul className="legend" aria-label="Legend">
      <li>
        <i className="st-eot" /> End of turn
      </li>
      <li>
        <i className="st-llm" /> LLM first token
      </li>
      <li>
        <i className="st-tts" /> TTS first audio
      </li>
    </ul>
  );
}
