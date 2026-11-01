import { useSyncExternalStore } from "react";
import type { TraceEvent, TurnSummary } from "../api/types";
import { isRecord, num, randomId } from "../lib/format";

export type Origin = "voice" | "chat" | "demo";

/** A trace event plus the bookkeeping the Inspector needs. */
export interface InspectorEvent extends TraceEvent {
  /** Monotonic arrival order across all runs. */
  seq: number;
  run: number;
  origin: Origin;
  /** `${run}:${turn}`: one timeline card per voice turn / chat message. */
  groupKey: string;
}

export interface Run {
  id: number;
  origin: Origin;
  label: string;
  startedAt: number;
}

export interface InspectorSnapshot {
  events: readonly InspectorEvent[];
  runs: readonly Run[];
  paused: boolean;
  /** Events received while paused, not yet shown. */
  buffered: number;
  /** Frames dropped because they were not a usable event object. */
  malformed: number;
  /** Oldest events discarded after hitting the cap. */
  dropped: number;
}

const MAX_EVENTS = 6000;

/**
 * Normalise anything that arrives on the wire into a TraceEvent, or null when
 * it is not an event at all. Unknown sources/types and missing optional fields
 * are tolerated: the Inspector must never break on a newer backend.
 */
export function normalizeTrace(raw: unknown): TraceEvent | null {
  if (!isRecord(raw)) return null;
  const source = typeof raw.source === "string" && raw.source ? raw.source : null;
  const type = typeof raw.type === "string" && raw.type ? raw.type : null;
  if (!source || !type) return null;
  const ts = num(raw.ts);
  const turn = num(raw.turn);
  const duration = num(raw.duration_ms);
  return {
    v: num(raw.v) ?? 1,
    id: typeof raw.id === "string" && raw.id ? raw.id : randomId("evt"),
    ts: ts ?? Date.now(),
    turn: turn != null ? Math.trunc(turn) : 0,
    source,
    type,
    label: typeof raw.label === "string" && raw.label ? raw.label : `${source}.${type}`,
    ...(duration != null ? { duration_ms: duration } : {}),
    data: isRecord(raw.data) ? raw.data : raw.data === undefined ? {} : { value: raw.data },
  };
}

class InspectorStore {
  private events: InspectorEvent[] = [];
  private pending: InspectorEvent[] = [];
  private runs: Run[] = [];
  private seen = new Set<string>();
  private nextSeq = 1;
  private nextRun = 1;
  private paused = false;
  private malformed = 0;
  private dropped = 0;
  private snapshot: InspectorSnapshot = this.build();
  private listeners = new Set<() => void>();
  private eventListeners = new Set<(e: InspectorEvent) => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;

  // ---- subscription (useSyncExternalStore)
  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
  getSnapshot = (): InspectorSnapshot => this.snapshot;

  /** Every ingested event, live, regardless of pause. Used by the voice transcript. */
  onEvent(l: (e: InspectorEvent) => void): () => void {
    this.eventListeners.add(l);
    return () => this.eventListeners.delete(l);
  }

  // ---- runs
  beginRun(origin: Origin, label: string): number {
    const run: Run = { id: this.nextRun++, origin, label, startedAt: Date.now() };
    this.runs = [...this.runs, run];
    this.touch();
    return run.id;
  }

  // ---- ingestion
  /** Decode a raw data-channel payload (UTF-8 JSON) and ingest it. */
  ingestRaw(payload: Uint8Array | string, run: number, origin: Origin): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(typeof payload === "string" ? payload : new TextDecoder().decode(payload));
    } catch {
      this.malformed++;
      this.touch();
      return;
    }
    this.ingest(parsed, run, origin);
  }

  ingest(raw: unknown, run: number, origin: Origin): InspectorEvent | null {
    const t = normalizeTrace(raw);
    if (!t) {
      this.malformed++;
      this.touch();
      return null;
    }
    const dedupe = `${run}:${t.id}`;
    if (this.seen.has(dedupe)) return null;
    this.seen.add(dedupe);

    const event: InspectorEvent = { ...t, seq: this.nextSeq++, run, origin, groupKey: `${run}:${t.turn}` };
    for (const l of this.eventListeners) l(event);
    if (this.paused) this.pending.push(event);
    else this.commit([event]);
    this.touch();
    return event;
  }

  private commit(batch: InspectorEvent[]): void {
    this.events = this.events.concat(batch);
    if (this.events.length > MAX_EVENTS) {
      const over = this.events.length - MAX_EVENTS;
      this.events = this.events.slice(over);
      this.dropped += over;
    }
  }

  // ---- controls
  pause(): void {
    this.paused = true;
    this.touch(true);
  }

  resume(): void {
    this.paused = false;
    if (this.pending.length) {
      this.commit(this.pending);
      this.pending = [];
    }
    this.touch(true);
  }

  clear(): void {
    this.events = [];
    this.pending = [];
    this.seen.clear();
    this.malformed = 0;
    this.dropped = 0;
    // Keep only runs that may still receive events (the newest of each origin).
    const latest = new Map<Origin, Run>();
    for (const r of this.runs) latest.set(r.origin, r);
    this.runs = [...latest.values()];
    this.touch(true);
  }

  /** All captured events (including any buffered while paused) as a JSON document. */
  exportJson(): string {
    const all = [...this.events, ...this.pending].sort((a, b) => a.seq - b.seq);
    const used = new Set(all.map((e) => e.run));
    return JSON.stringify(
      {
        exported_at: new Date().toISOString(),
        app: "omnivox-inspector",
        schema: "omnivox.trace/v1",
        runs: this.runs.filter((r) => used.has(r.id)),
        events: all.map(({ seq: _s, groupKey: _g, ...rest }) => rest),
      },
      null,
      2,
    );
  }

  // ---- internals
  private build(): InspectorSnapshot {
    return {
      events: this.events,
      runs: this.runs,
      paused: this.paused,
      buffered: this.pending.length,
      malformed: this.malformed,
      dropped: this.dropped,
    };
  }

  /** Publish a new snapshot, coalescing bursts (events can arrive every few ms). */
  private touch(immediate = false): void {
    const flush = () => {
      this.timer = null;
      this.snapshot = this.build();
      for (const l of this.listeners) l();
    };
    if (immediate) {
      if (this.timer) clearTimeout(this.timer);
      flush();
    } else if (!this.timer) {
      this.timer = setTimeout(flush, 40);
    }
  }
}

export const inspectorStore = new InspectorStore();

export function useInspector(): InspectorSnapshot {
  return useSyncExternalStore(inspectorStore.subscribe, inspectorStore.getSnapshot);
}

// ------------------------------------------------------------------ grouping

export interface TurnGroup {
  key: string;
  run: number;
  turn: number;
  origin: Origin;
  runLabel: string;
  events: InspectorEvent[];
  startTs: number;
  endTs: number;
  /** What the user said / typed, when known. */
  userText?: string;
  summary?: Partial<TurnSummary>;
  hasError: boolean;
  toolCount: number;
}

/** Chat turns only know some stages, so every field is optional. */
export function readSummary(data: Record<string, unknown>): Partial<TurnSummary> {
  return {
    eot_ms: num(data.eot_ms),
    llm_ttft_ms: num(data.llm_ttft_ms),
    tts_ttfb_ms: num(data.tts_ttfb_ms),
    total_ms: num(data.total_ms),
  };
}

/** Group events into per-turn cards, in arrival order of each group's first event. */
export function groupEvents(events: readonly InspectorEvent[], runs: readonly Run[]): TurnGroup[] {
  const runLabel = new Map(runs.map((r) => [r.id, r.label]));
  const groups = new Map<string, TurnGroup>();
  for (const e of events) {
    let g = groups.get(e.groupKey);
    if (!g) {
      g = {
        key: e.groupKey,
        run: e.run,
        turn: e.turn,
        origin: e.origin,
        runLabel: runLabel.get(e.run) ?? "",
        events: [],
        startTs: e.ts,
        endTs: e.ts,
        hasError: false,
        toolCount: 0,
      };
      groups.set(e.groupKey, g);
    }
    g.events.push(e);
    g.startTs = Math.min(g.startTs, e.ts);
    g.endTs = Math.max(g.endTs, e.ts + (e.duration_ms ?? 0));
    if (e.source === "error" || (e.source === "tool" && e.type === "error")) g.hasError = true;
    if (e.source === "tool" && e.type === "start") g.toolCount++;
    if (e.source === "stt" && e.type === "final" && typeof e.data.text === "string") g.userText = e.data.text;
    if (e.source === "session" && e.type === "user_message" && typeof e.data.text === "string") g.userText = e.data.text;
    if (e.source === "latency" && e.type === "turn_summary") g.summary = readSummary(e.data);
  }
  const out = [...groups.values()];
  for (const g of out) g.events.sort((a, b) => a.ts - b.ts || a.seq - b.seq);
  return out;
}
