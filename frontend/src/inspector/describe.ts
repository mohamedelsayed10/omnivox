import { KNOWN_SOURCES, type TraceEvent } from "../api/types";
import { formatMs, isRecord, num, str, truncate } from "../lib/format";

/** Filter-chip key for an event source; anything not in the contract folds into "other". */
export type SourceKey = (typeof KNOWN_SOURCES)[number] | "other";

export const SOURCE_KEYS: readonly SourceKey[] = [...KNOWN_SOURCES, "other"];

export function sourceKey(source: string): SourceKey {
  return (KNOWN_SOURCES as readonly string[]).includes(source) ? (source as SourceKey) : "other";
}

export const SOURCE_LABELS: Record<SourceKey, string> = {
  session: "session",
  vad: "vad",
  stt: "stt",
  eot: "eot",
  graph: "graph",
  tool: "tool",
  llm: "llm",
  tts: "tts",
  latency: "latency",
  error: "error",
  other: "other",
};

function scalar(v: unknown): string {
  if (v == null) return String(v);
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function compactArgs(args: unknown): string {
  if (args == null) return "";
  if (!isRecord(args)) return truncate(scalar(args), 60);
  return truncate(
    Object.entries(args)
      .map(([k, v]) => `${k}: ${scalar(v)}`)
      .join(", "),
    80,
  );
}

/** One-line human summary of an event's `data`. Never throws, whatever the payload. */
export function summarize(e: TraceEvent): string {
  const d = e.data;
  const ms = (v: unknown) => formatMs(num(v));
  switch (`${e.source}.${e.type}`) {
    case "session.agent_state":
    case "vad.user_state":
      return str(d.state) ?? "";
    case "stt.interim":
    case "stt.final": {
      const text = str(d.text);
      const lang = str(d.language);
      return text != null ? `“${truncate(text, 120)}”${lang ? `  [${lang}]` : ""}` : "";
    }
    case "eot.detected": {
      const t = num(d.transcript_delay_ms);
      return `delay ${ms(d.delay_ms)}${t != null ? ` · transcript ${formatMs(t)}` : ""}`;
    }
    case "graph.node_start":
    case "graph.node_end":
      return str(d.node) ?? "";
    case "graph.route":
      return `${scalar(d.from)} → ${scalar(d.to)}`;
    case "tool.start":
      return `${scalar(d.name)}(${compactArgs(d.args)})`;
    case "tool.end":
      return `${scalar(d.name)} → ${truncate(scalar(d.result_preview ?? ""), 100)}`;
    case "tool.error":
      return `${scalar(d.name)}: ${truncate(scalar(d.message ?? ""), 100)}`;
    case "llm.start":
      return scalar(d.model ?? "");
    case "llm.first_token":
      return `ttft ${ms(d.ttft_ms)}`;
    case "llm.end":
      return `${scalar(d.input_tokens ?? "?")} in · ${scalar(d.output_tokens ?? "?")} out · ${scalar(d.finish_reason ?? "?")}`;
    case "tts.start":
      return `${scalar(d.characters ?? "?")} chars`;
    case "tts.first_audio":
      return `ttfb ${ms(d.ttfb_ms)}`;
    case "tts.end":
      return `${ms(d.audio_ms)} of audio`;
    case "latency.turn_summary":
      return `total ${ms(d.total_ms)}`;
    case "error.error":
      return truncate(scalar(d.message ?? ""), 140);
    case "session.user_message":
      return `“${truncate(scalar(d.text ?? ""), 120)}”`;
    case "session.final":
      return `${scalar(d.characters ?? "?")} characters`;
    case "session.invoke_response": {
      const tools = Array.isArray(d.tools_used) ? d.tools_used.length : 0;
      return `${scalar(d.characters ?? "?")} characters · ${tools} tool${tools === 1 ? "" : "s"}`;
    }
    default: {
      // Unknown event: show the first few scalar fields so it is still useful.
      const parts: string[] = [];
      for (const [k, v] of Object.entries(d)) {
        if (parts.length >= 3) break;
        parts.push(`${k}: ${truncate(scalar(v), 40)}`);
      }
      return parts.join(" · ");
    }
  }
}

/** Searchable text for an event: identity fields plus the serialised data. */
export function searchText(e: TraceEvent): string {
  let data = "";
  try {
    data = JSON.stringify(e.data);
  } catch {
    /* ignore */
  }
  return `${e.source} ${e.type} ${e.label} ${data}`.toLowerCase();
}

export function isKnownPair(e: TraceEvent): boolean {
  return KNOWN_PAIRS.has(`${e.source}.${e.type}`);
}

const KNOWN_PAIRS = new Set([
  "session.agent_state",
  "vad.user_state",
  "stt.interim",
  "stt.final",
  "eot.detected",
  "graph.node_start",
  "graph.node_end",
  "graph.route",
  "tool.start",
  "tool.end",
  "tool.error",
  "llm.start",
  "llm.first_token",
  "llm.end",
  "tts.start",
  "tts.first_audio",
  "tts.end",
  "latency.turn_summary",
  "error.error",
  // emitted by the chat tracer
  "session.user_message",
  "session.final",
  "session.invoke_response",
]);
