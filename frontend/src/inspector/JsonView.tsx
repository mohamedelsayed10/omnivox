import { useMemo, type ReactNode } from "react";

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "undefined";
  } catch {
    return String(value);
  }
}

/** Pretty-printed, syntax-coloured JSON. Built from React nodes, never innerHTML. */
export function JsonView({ value }: { value: unknown }) {
  const nodes = useMemo(() => highlight(prettyJson(value)), [value]);
  return (
    <pre className="json" tabIndex={0} aria-label="Event data (JSON)">
      {nodes}
    </pre>
  );
}

function highlight(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const [full, str, colon, lit] = m;
    if (str !== undefined) {
      if (colon) {
        out.push(
          <span key={i++} className="j-key">
            {str}
          </span>,
          colon,
        );
      } else {
        out.push(
          <span key={i++} className="j-str">
            {str}
          </span>,
        );
      }
    } else if (lit !== undefined) {
      out.push(
        <span key={i++} className={lit === "null" ? "j-null" : "j-bool"}>
          {full}
        </span>,
      );
    } else {
      out.push(
        <span key={i++} className="j-num">
          {full}
        </span>,
      );
    }
    last = at + full.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
