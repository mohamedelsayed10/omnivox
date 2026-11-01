import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Bot, Check, Loader2, MessageSquarePlus, Send, Sparkles, Square, Wrench, XCircle } from "lucide-react";
import { CopyButton } from "../components/CopyButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { Markdown } from "../components/Markdown";
import { JsonView } from "../inspector/JsonView";
import { formatMs } from "../lib/format";
import { useChat, type ChatMessage, type ToolStep } from "../state/chat";

const SUGGESTIONS = [
  "What does the knowledge base say about the latency budget?",
  "Search the web for the latest Qdrant release",
  "Explain how a voice turn flows through OmniVox",
];

export function ChatView() {
  const { messages, sessionId, busy, streamTokens, setStreamTokens, send, stop, newSession } = useChat();
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);

  // Keep the latest message in view unless the user scrolled up to read.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [draft]);

  const submit = () => {
    if (!draft.trim() || busy) return;
    stick.current = true;
    send(draft);
    setDraft("");
  };

  return (
    <section className="view chat" aria-label="Text chat">
      <div className="chat-bar">
        <div className="session-chip" title="Session id sent with every request">
          <span className="label">Session</span>
          <code className="mono">{sessionId}</code>
          <CopyButton text={sessionId} label="Copy session id" />
        </div>
        <div className="chat-bar-actions">
          <label className="toggle" title="Off uses POST /agent/invoke and returns the full answer at once">
            <input
              type="checkbox"
              role="switch"
              checked={streamTokens}
              disabled={busy}
              onChange={(e) => setStreamTokens(e.target.checked)}
            />
            <span className="track" aria-hidden />
            <span>Stream tokens</span>
          </label>
          <button className="btn btn-sm" onClick={newSession} title="Start a new session (clears this conversation)">
            <MessageSquarePlus size={15} /> New session
          </button>
        </div>
      </div>

      <div
        className="chat-list card"
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64;
        }}
      >
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-orb" aria-hidden>
              <Sparkles size={26} />
            </div>
            <h2>Ask the agent anything</h2>
            <p>Answers stream in token by token. Open the Inspector to watch the graph, tools and latency of every message.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="msgs" aria-live="polite" aria-label="Conversation">
            {messages.map((m) => (
              <MessageItem key={m.id} m={m} />
            ))}
          </ol>
        )}
      </div>

      <form
        className="composer card"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <textarea
          id="chat-input"
          ref={taRef}
          className="textarea"
          rows={1}
          placeholder="Message OmniVox…"
          title="Enter to send, Shift+Enter for a new line"
          value={draft}
          maxLength={8000}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {busy ? (
          <button type="button" className="btn btn-danger" onClick={stop} aria-label="Stop generating">
            <Square size={14} fill="currentColor" /> Stop
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!draft.trim()} aria-label="Send message">
            <Send size={16} /> <span className="send-label">Send</span>
          </button>
        )}
      </form>
    </section>
  );
}

function MessageItem({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <li className="msg user">
        <div className="bubble">{m.text}</div>
      </li>
    );
  }
  const live = m.status === "pending" || m.status === "streaming";
  return (
    <li className="msg bot">
      <div className="avatar" aria-hidden>
        <Bot size={16} />
      </div>
      <div className="msg-col">
        {m.tools.length > 0 && (
          <div className="tools" aria-label="Tool calls">
            {m.tools.map((t) => (
              <ToolChip key={t.id} t={t} />
            ))}
          </div>
        )}
        {m.toolsUsed && m.toolsUsed.length > 0 && (
          <div className="tools" aria-label="Tools used">
            {m.toolsUsed.map((t) => (
              <span key={t} className="tool-chip done">
                <Wrench size={12} /> {t}
              </span>
            ))}
          </div>
        )}
        {(m.text || live) && (
          <div className={`bubble${live ? " live" : ""}`}>
            {m.status === "pending" && !m.text ? (
              <span className="typing" aria-label="Thinking">
                <i />
                <i />
                <i />
              </span>
            ) : (
              <>
                <Markdown text={m.text} />
                {m.status === "streaming" && <span className="caret" aria-hidden />}
              </>
            )}
          </div>
        )}
        {m.status === "stopped" && <div className="msg-note">Stopped</div>}
        {m.error && (
          <div style={{ marginTop: 8 }}>
            <ErrorBanner error={m.error} title="The agent could not answer" />
          </div>
        )}
        {m.status === "done" && (m.durationMs != null || m.requestId) && (
          <div className="msg-note mono">
            {m.durationMs != null && formatMs(m.durationMs)}
            {m.requestId && <> · {m.requestId}</>}
          </div>
        )}
      </div>
    </li>
  );
}

function ToolChip({ t }: { t: ToolStep }) {
  const icon =
    t.status === "running" ? (
      <Loader2 size={12} className="spin" />
    ) : t.status === "error" ? (
      <XCircle size={12} />
    ) : (
      <Check size={12} />
    );
  const hasDetail = t.args != null || t.preview || t.message;
  return (
    <details className={`tool-step ${t.status}`}>
      <summary className={`tool-chip ${t.status}`} aria-disabled={!hasDetail}>
        <Wrench size={12} aria-hidden />
        <span className="mono">{t.name}</span>
        {icon}
        {t.durationMs != null && <span className="mono dim">{formatMs(t.durationMs)}</span>}
      </summary>
      {hasDetail && (
        <div className="tool-detail">
          <JsonView
            value={{
              ...(t.args != null ? { args: t.args } : {}),
              ...(t.preview ? { result_preview: t.preview } : {}),
              ...(t.message ? { error: t.message } : {}),
            }}
          />
        </div>
      )}
    </details>
  );
}
