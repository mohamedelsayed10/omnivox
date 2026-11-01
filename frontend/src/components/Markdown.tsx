import { Fragment, type ReactNode } from "react";

/**
 * A deliberately small Markdown renderer for assistant answers: paragraphs,
 * headings, lists, fenced/inline code, bold, italics and http(s) links. It
 * builds React elements only (no HTML injection), and tolerates half-finished
 * input while a response is still streaming.
 */

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g;

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (m[1]) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (m[3]) out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    else {
      const mm = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(tok);
      out.push(
        mm ? (
          <a key={key} href={mm[2]} target="_blank" rel="noreferrer noopener">
            {mm[1]}
          </a>
        ) : (
          tok
        ),
      );
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: number; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; lang: string; text: string };

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] as string;
    const fence = /^```\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i] as string)) body.push(lines[i++] as string);
      i++; // closing fence (absent while streaming)
      blocks.push({ kind: "code", lang: fence[1] ?? "", text: body.join("\n") });
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ kind: "h", level: (h[1] as string).length, text: h[2] as string });
      i++;
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const re = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*•]\s+(.*)$/;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i] as string)) items.push((re.exec(lines[i++] as string) as RegExpExecArray)[1] as string);
      blocks.push({ kind: ordered ? "ol" : "ul", items });
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      (lines[i] as string).trim() &&
      !/^```/.test(lines[i] as string) &&
      !/^#{1,4}\s/.test(lines[i] as string) &&
      !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i] as string)
    ) {
      para.push(lines[i++] as string);
    }
    blocks.push({ kind: "p", lines: para });
  }
  return blocks;
}

export function Markdown({ text }: { text: string }) {
  const blocks = parse(text);
  return (
    <div className="md">
      {blocks.map((b, bi) => {
        const key = `b${bi}`;
        switch (b.kind) {
          case "code":
            return (
              <pre key={key} className="md-code" data-lang={b.lang || undefined}>
                <code>{b.text}</code>
              </pre>
            );
          case "h":
            return (
              <p key={key} className="md-h" data-level={b.level}>
                {inline(b.text, key)}
              </p>
            );
          case "ul":
          case "ol": {
            const List = b.kind;
            return (
              <List key={key}>
                {b.items.map((it, ii) => (
                  <li key={ii}>{inline(it, `${key}-${ii}`)}</li>
                ))}
              </List>
            );
          }
          default:
            return (
              <p key={key}>
                {b.lines.map((l, li) => (
                  <Fragment key={li}>
                    {li > 0 && <br />}
                    {inline(l, `${key}-${li}`)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
