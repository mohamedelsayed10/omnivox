import { memo } from "react";
import { AlertTriangle, ChevronRight, FlaskConical, MessageSquare, Mic, Wrench } from "lucide-react";
import { formatClock, formatMs, formatOffset } from "../lib/format";
import { CopyButton } from "../components/CopyButton";
import { isKnownPair, sourceKey, summarize } from "./describe";
import { JsonView, prettyJson } from "./JsonView";
import type { InspectorEvent, TurnGroup } from "./store";
import { Waterfall } from "./Waterfall";

export interface VisibleGroup {
  group: TurnGroup;
  /** Events that pass the current filters. */
  events: InspectorEvent[];
}

export function Timeline({
  groups,
  isExpanded,
  onToggleGroup,
  expandedEvents,
  onToggleEvent,
}: {
  groups: VisibleGroup[];
  isExpanded: (g: TurnGroup) => boolean;
  onToggleGroup: (g: TurnGroup) => void;
  expandedEvents: ReadonlySet<number>;
  onToggleEvent: (seq: number) => void;
}) {
  return (
    <ol className="turns">
      {groups.map(({ group, events }) => (
        <TurnCard
          key={group.key}
          group={group}
          events={events}
          expanded={isExpanded(group)}
          onToggle={() => onToggleGroup(group)}
          expandedEvents={expandedEvents}
          onToggleEvent={onToggleEvent}
        />
      ))}
    </ol>
  );
}

function originIcon(origin: TurnGroup["origin"]) {
  if (origin === "chat") return <MessageSquare size={14} aria-hidden />;
  if (origin === "demo") return <FlaskConical size={14} aria-hidden />;
  return <Mic size={14} aria-hidden />;
}

const TurnCard = memo(function TurnCard({
  group,
  events,
  expanded,
  onToggle,
  expandedEvents,
  onToggleEvent,
}: {
  group: TurnGroup;
  events: InspectorEvent[];
  expanded: boolean;
  onToggle: () => void;
  expandedEvents: ReadonlySet<number>;
  onToggleEvent: (seq: number) => void;
}) {
  const title = group.turn === 0 ? "Session" : `Turn ${group.turn}`;
  const total = group.summary?.total_ms ?? group.endTs - group.startTs;
  const span = Math.max(1, group.endTs - group.startTs);

  return (
    <li className={`turn${group.hasError ? " has-error" : ""}`}>
      <button
        className="turn-head"
        aria-expanded={expanded}
        onClick={onToggle}
        aria-label={`${title}, ${group.runLabel}, ${events.length} events${group.userText ? `, “${group.userText}”` : ""}`}
      >
        <ChevronRight size={16} className="chev" aria-hidden />
        <span className="turn-title">
          {originIcon(group.origin)}
          <span>{title}</span>
        </span>
        <span className="turn-snippet">{group.userText ? `“${group.userText}”` : group.runLabel}</span>
        <span className="turn-meta">
          {group.hasError && <AlertTriangle size={14} color="var(--err)" aria-label="Contains an error" />}
          {group.toolCount > 0 && (
            <span className="mini">
              <Wrench size={12} aria-hidden /> {group.toolCount}
            </span>
          )}
          <span className="mini mono">{events.length}</span>
          {group.turn !== 0 && total > 0 && <span className="mini mono strong">{formatMs(total)}</span>}
        </span>
      </button>

      {expanded && (
        <div className="turn-body">
          {group.runLabel && <div className="turn-run">{group.runLabel}</div>}
          {group.summary && (
            <div className="turn-wf">
              <Waterfall summary={group.summary} compact />
            </div>
          )}
          {events.length === 0 ? (
            <p className="muted-note" style={{ padding: "6px 4px" }}>
              No events match the current filters.
            </p>
          ) : (
            <ol className="events">
              {events.map((e) => (
                <EventRow
                  key={e.seq}
                  e={e}
                  t0={group.startTs}
                  span={span}
                  expanded={expandedEvents.has(e.seq)}
                  onToggle={onToggleEvent}
                />
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  );
});

const EventRow = memo(function EventRow({
  e,
  t0,
  span,
  expanded,
  onToggle,
}: {
  e: InspectorEvent;
  t0: number;
  span: number;
  expanded: boolean;
  onToggle: (seq: number) => void;
}) {
  const key = sourceKey(e.source);
  const known = isKnownPair(e);
  const sum = summarize(e);
  const offset = e.ts - t0;
  // Gantt-style hint: events with a duration are positioned on the turn's time span.
  const dur = e.duration_ms;
  const barStart = dur != null ? Math.max(0, offset - dur) : offset;
  const barWidth = dur != null ? dur : 0;

  return (
    <li className={`ev src-${key}${e.source === "error" || e.type === "error" ? " is-error" : ""}`}>
      <button
        className="ev-head"
        aria-expanded={expanded}
        onClick={() => onToggle(e.seq)}
        style={
          dur != null
            ? ({
                "--bar-l": `${Math.min(99, (barStart / span) * 100)}%`,
                "--bar-w": `${Math.max(0.8, Math.min(100, (barWidth / span) * 100))}%`,
              } as React.CSSProperties)
            : undefined
        }
      >
        <span className="ev-time mono" title={formatClock(e.ts)}>
          {formatOffset(offset)}
        </span>
        <span className={`badge src-${key}`} title={e.source}>
          {key === "other" ? e.source.slice(0, 9) : key}
        </span>
        <span className="ev-main">
          <span className="ev-label">
            {e.label}
            {!known && (
              <span className="ev-unknown" title="Unrecognised event type; shown generically">
                {e.source}.{e.type}
              </span>
            )}
          </span>
          {sum && <span className="ev-sum">{sum}</span>}
        </span>
        {dur != null && <span className="ev-dur mono">{formatMs(dur)}</span>}
        <ChevronRight size={14} className="chev" aria-hidden />
      </button>

      {expanded && (
        <div className="ev-body">
          <div className="ev-meta mono">
            <span>
              {e.source}.{e.type}
            </span>
            <span>turn {e.turn}</span>
            <span>{formatClock(e.ts)}</span>
            <span title="event id">{e.id}</span>
            {e.v !== 1 && <span>v{e.v}</span>}
            <CopyButton text={prettyJson(e.data)} label="Copy data as JSON" />
          </div>
          <JsonView value={e.data} />
        </div>
      )}
    </li>
  );
});
