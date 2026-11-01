import { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Download,
  FlaskConical,
  Gauge,
  ListTree,
  Pause,
  Play,
  Radar,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useDemo } from "../dev/demoContext";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";
import { INSPECTOR_MAX, INSPECTOR_MIN, useLayout } from "../state/layout";
import { SOURCE_KEYS, searchText, sourceKey, type SourceKey } from "./describe";
import { LatencyPanel } from "./LatencyPanel";
import { groupEvents, inspectorStore, useInspector, type TurnGroup } from "./store";
import { Timeline, type VisibleGroup } from "./Timeline";

type Tab = "timeline" | "latency";

function download(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Inspector() {
  const { docked, mobile, inspectorVisible, inspectorWidth, closeInspector } = useLayout();
  const snap = useInspector();
  const demo = useDemo();

  const [tab, setTab] = useState<Tab>("timeline");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const [enabled, setEnabled] = useState<ReadonlySet<SourceKey>>(() => new Set(SOURCE_KEYS));
  const [groupOverride, setGroupOverride] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const [expandedEvents, setExpandedEvents] = useState<ReadonlySet<number>>(() => new Set());
  const [autoScroll, setAutoScroll] = useState(() => readStorage(STORAGE_KEYS.autoScroll) !== "0");
  const scrollRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const groups = useMemo(() => groupEvents(snap.events, snap.runs), [snap.events, snap.runs]);
  const latestKey = groups.length ? groups[groups.length - 1]!.key : "";

  // Per-source counts for the filter chips (over everything, not the filtered view).
  const counts = useMemo(() => {
    const c = new Map<SourceKey, number>();
    for (const e of snap.events) c.set(sourceKey(e.source), (c.get(sourceKey(e.source)) ?? 0) + 1);
    return c;
  }, [snap.events]);

  const visible = useMemo<VisibleGroup[]>(() => {
    const out: VisibleGroup[] = [];
    for (const group of groups) {
      const events = group.events.filter(
        (e) => enabled.has(sourceKey(e.source)) && (!deferredQuery || searchText(e).includes(deferredQuery)),
      );
      if (events.length || (!deferredQuery && enabled.size === SOURCE_KEYS.length)) out.push({ group, events });
    }
    return out;
  }, [groups, enabled, deferredQuery]);

  const filtering = enabled.size !== SOURCE_KEYS.length || deferredQuery !== "";
  const shownEvents = visible.reduce((n, v) => n + v.events.length, 0);

  const isExpanded = useCallback(
    (g: TurnGroup) => (deferredQuery ? true : (groupOverride.get(g.key) ?? g.key === latestKey)),
    [groupOverride, latestKey, deferredQuery],
  );
  const onToggleGroup = useCallback(
    (g: TurnGroup) =>
      setGroupOverride((m) => {
        const next = new Map(m);
        next.set(g.key, !isExpanded(g));
        return next;
      }),
    [isExpanded],
  );
  const onToggleEvent = useCallback(
    (seq: number) =>
      setExpandedEvents((s) => {
        const next = new Set(s);
        if (next.has(seq)) next.delete(seq);
        else next.add(seq);
        return next;
      }),
    [],
  );

  // Follow new events.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (tab === "latency") el.scrollTop = 0;
    else if (autoScroll) el.scrollTop = el.scrollHeight;
  }, [autoScroll, tab, visible, shownEvents, expandedEvents, inspectorVisible]);

  useEffect(() => {
    if (inspectorVisible && !docked) closeRef.current?.focus();
  }, [inspectorVisible, docked]);

  useEffect(() => {
    if (!inspectorVisible || docked) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeInspector();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [inspectorVisible, docked, closeInspector]);

  if (!inspectorVisible) return null;

  const toggleSource = (k: SourceKey) =>
    setEnabled((s) => {
      const next = new Set(s);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const setAuto = (on: boolean) => {
    setAutoScroll(on);
    writeStorage(STORAGE_KEYS.autoScroll, on ? "1" : "0");
  };

  const total = snap.events.length;
  const body = (
    <aside
      className={`inspector ${docked ? "docked" : "drawer"}${mobile ? " sheet" : ""}`}
      style={docked || !mobile ? { width: docked ? inspectorWidth : `min(${inspectorWidth}px, 100vw)` } : undefined}
      aria-label="Inspector"
      role={docked ? "complementary" : "dialog"}
      aria-modal={docked ? undefined : true}
    >
      {docked && <ResizeHandle />}

      <div className="insp-head">
        <div className="insp-title">
          <Radar size={18} aria-hidden />
          <h2>Inspector</h2>
          <span className={`live ${snap.paused ? "paused" : ""}`} role="status">
            <i aria-hidden />
            {snap.paused ? `Paused${snap.buffered ? ` · ${snap.buffered} buffered` : ""}` : "Live"}
          </span>
        </div>
        <div className="insp-actions">
          <button
            className="btn btn-sm btn-icon"
            onClick={() => (snap.paused ? inspectorStore.resume() : inspectorStore.pause())}
            aria-label={snap.paused ? "Resume" : "Pause"}
            title={snap.paused ? "Resume (show buffered events)" : "Pause (buffer new events)"}
            aria-pressed={snap.paused}
          >
            {snap.paused ? <Play size={15} /> : <Pause size={15} />}
          </button>
          <button
            className="btn btn-sm btn-icon"
            onClick={() => setAuto(!autoScroll)}
            aria-pressed={autoScroll}
            aria-label="Auto-scroll"
            title="Auto-scroll to newest event"
          >
            <ArrowDownToLine size={15} />
          </button>
          <button
            className="btn btn-sm btn-icon"
            onClick={() => download(`omnivox-trace-${new Date().toISOString().replace(/[:.]/g, "-")}.json`, inspectorStore.exportJson())}
            disabled={total + snap.buffered === 0}
            aria-label="Export events as JSON"
            title="Export JSON"
          >
            <Download size={15} />
          </button>
          <button
            className="btn btn-sm btn-icon"
            onClick={() => {
              inspectorStore.clear();
              setGroupOverride(new Map());
              setExpandedEvents(new Set());
            }}
            disabled={total + snap.buffered === 0}
            aria-label="Clear events"
            title="Clear"
          >
            <Trash2 size={15} />
          </button>
          <button ref={closeRef} className="btn btn-sm btn-icon btn-ghost" onClick={closeInspector} aria-label="Close Inspector" title="Close">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="insp-tools">
        <div className="input-wrap">
          <Search size={15} aria-hidden />
          <input
            className="input"
            type="search"
            placeholder="Search events…"
            aria-label="Search events"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ minHeight: 34 }}
          />
        </div>
        <div className="filters" role="group" aria-label="Filter by source">
          {SOURCE_KEYS.filter((k) => k !== "other" || (counts.get("other") ?? 0) > 0).map((k) => {
            const on = enabled.has(k);
            return (
              <button
                key={k}
                className={`filter src-${k}${on ? " on" : ""}`}
                aria-pressed={on}
                onClick={() => toggleSource(k)}
              >
                <i aria-hidden />
                {k}
                <span className="n">{counts.get(k) ?? 0}</span>
              </button>
            );
          })}
          {enabled.size !== SOURCE_KEYS.length && (
            <button className="filter-reset" onClick={() => setEnabled(new Set(SOURCE_KEYS))}>
              show all
            </button>
          )}
        </div>
        {(snap.malformed > 0 || snap.dropped > 0) && (
          <div className="insp-warn" role="status">
            {snap.malformed > 0 && <span>{snap.malformed} malformed frame{snap.malformed === 1 ? "" : "s"} ignored</span>}
            {snap.dropped > 0 && <span>oldest {snap.dropped} events trimmed</span>}
          </div>
        )}
      </div>

      <div className="insp-tabs" role="tablist" aria-label="Inspector views">
        <TabButton id="timeline" current={tab} onSelect={setTab} icon={<ListTree size={15} />}>
          Timeline
          <span className="n">{filtering ? `${shownEvents}/${total}` : total}</span>
        </TabButton>
        <TabButton id="latency" current={tab} onSelect={setTab} icon={<Gauge size={15} />}>
          Latency
        </TabButton>
      </div>

      <div
        className="insp-body"
        ref={scrollRef}
        role="tabpanel"
        aria-label={tab === "timeline" ? "Timeline" : "Latency"}
        onWheel={(e) => {
          if (e.deltaY < 0 && autoScroll) setAuto(false);
        }}
      >
        {tab === "latency" ? (
          <LatencyPanel groups={groups} />
        ) : total === 0 && snap.buffered === 0 ? (
          <div className="empty">
            <Radar size={30} aria-hidden />
            <strong>Nothing traced yet</strong>
            <span>
              Start a voice call or send a chat message. Every VAD, STT, end-of-turn, graph, tool, LLM and TTS step shows
              up here.
            </span>
            {demo && (
              <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => demo.start()} disabled={demo.starting}>
                <FlaskConical size={14} /> Replay sample call
              </button>
            )}
          </div>
        ) : visible.length === 0 ? (
          <div className="empty">
            <Search size={26} aria-hidden />
            <strong>No events match</strong>
            <span>Adjust the search or source filters.</span>
          </div>
        ) : (
          <Timeline
            groups={visible}
            isExpanded={isExpanded}
            onToggleGroup={onToggleGroup}
            expandedEvents={expandedEvents}
            onToggleEvent={onToggleEvent}
          />
        )}
      </div>
    </aside>
  );

  if (docked) return body;
  return (
    <>
      <div className="insp-backdrop" onClick={closeInspector} aria-hidden />
      {body}
    </>
  );
}

function TabButton({
  id,
  current,
  onSelect,
  icon,
  children,
}: {
  id: Tab;
  current: Tab;
  onSelect: (t: Tab) => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={current === id}
      className={current === id ? "on" : ""}
      onClick={() => onSelect(id)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") onSelect(id === "timeline" ? "latency" : "timeline");
      }}
    >
      {icon}
      {children}
    </button>
  );
}

/** Drag (pointer) or arrow-key handle on the Inspector's left edge. */
function ResizeHandle() {
  const { inspectorWidth, setInspectorWidth } = useLayout();
  const drag = useRef<{ x: number; w: number } | null>(null);

  return (
    <div
      className="resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize Inspector"
      aria-valuemin={INSPECTOR_MIN}
      aria-valuemax={INSPECTOR_MAX}
      aria-valuenow={inspectorWidth}
      tabIndex={0}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, w: inspectorWidth };
        document.body.classList.add("resizing");
      }}
      onPointerMove={(e) => {
        if (drag.current) setInspectorWidth(drag.current.w + (drag.current.x - e.clientX));
      }}
      onPointerUp={(e) => {
        drag.current = null;
        e.currentTarget.releasePointerCapture(e.pointerId);
        document.body.classList.remove("resizing");
      }}
      onDoubleClick={() => setInspectorWidth(440)}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 64 : 16;
        if (e.key === "ArrowLeft") setInspectorWidth(inspectorWidth + step);
        else if (e.key === "ArrowRight") setInspectorWidth(inspectorWidth - step);
        else if (e.key === "Home") setInspectorWidth(INSPECTOR_MAX);
        else if (e.key === "End") setInspectorWidth(INSPECTOR_MIN);
        else return;
        e.preventDefault();
      }}
    />
  );
}
