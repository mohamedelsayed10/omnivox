import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, describeError, streamAgent } from "../api/client";
import type { StreamFrame } from "../api/types";
import type { UiError } from "../components/ErrorBanner";
import { ChatTracer } from "../inspector/chatTrace";
import { inspectorStore } from "../inspector/store";
import { randomId } from "../lib/format";
import { readStorage, STORAGE_KEYS, writeStorage } from "../lib/storage";

export interface ToolStep {
  id: number;
  name: string;
  status: "running" | "done" | "error";
  args?: unknown;
  preview?: string;
  durationMs?: number;
  message?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  status: "pending" | "streaming" | "done" | "error" | "stopped";
  tools: ToolStep[];
  /** Only set by the non-streaming /invoke path. */
  toolsUsed?: string[];
  error?: UiError;
  requestId?: string;
  durationMs?: number;
}

interface ChatApi {
  messages: ChatMessage[];
  sessionId: string;
  busy: boolean;
  streamTokens: boolean;
  setStreamTokens: (v: boolean) => void;
  send: (text: string) => void;
  stop: () => void;
  newSession: () => void;
}

const Ctx = createContext<ChatApi | null>(null);

/** Session ids must be 1..64 characters. */
function makeSessionId(): string {
  return randomId("web").slice(0, 64);
}

function initialSessionId(): string {
  const stored = readStorage(STORAGE_KEYS.sessionId);
  if (stored && stored.length >= 1 && stored.length <= 64) return stored;
  const id = makeSessionId();
  writeStorage(STORAGE_KEYS.sessionId, id);
  return id;
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [busy, setBusy] = useState(false);
  const [streamTokens, setStream] = useState(() => readStorage(STORAGE_KEYS.streamTokens) !== "0");

  const ctl = useRef<AbortController | null>(null);
  const turnRef = useRef(0);
  const runRef = useRef<{ session: string; run: number } | null>(null);
  const toolSeq = useRef(0);

  useEffect(() => () => ctl.current?.abort(), []);

  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const setStreamTokens = useCallback((v: boolean) => {
    writeStorage(STORAGE_KEYS.streamTokens, v ? "1" : "0");
    setStream(v);
  }, []);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || busy) return;

      if (runRef.current?.session !== sessionId) {
        runRef.current = {
          session: sessionId,
          run: inspectorStore.beginRun("chat", `Chat · ${sessionId.slice(0, 12)}`),
        };
        turnRef.current = 0;
      }
      const turn = ++turnRef.current;
      const tracer = new ChatTracer(runRef.current.run, turn, sessionId);
      tracer.userMessage(text);

      const userMsg: ChatMessage = { id: randomId("u"), role: "user", text, status: "done", tools: [] };
      const botId = randomId("a");
      setMessages((l) => [...l, userMsg, { id: botId, role: "assistant", text: "", status: "pending", tools: [] }]);
      setBusy(true);

      const controller = new AbortController();
      ctl.current = controller;
      const started = performance.now();

      // Tokens arrive every few ms; coalesce them into ~30 renders/s.
      let acc = "";
      let flushTimer: number | undefined;
      const flush = () => {
        flushTimer = undefined;
        patch(botId, (m) => ({ ...m, text: acc, status: m.status === "pending" ? "streaming" : m.status }));
      };

      const onFrame = (f: StreamFrame) => {
        tracer.frame(f);
        switch (f.event) {
          case "tool": {
            const d = f.data;
            patch(botId, (m) => {
              const tools = [...m.tools];
              if (d.phase === "start") {
                tools.push({ id: ++toolSeq.current, name: d.name, status: "running", args: d.args });
              } else {
                const i = tools.map((t) => t.name === d.name && t.status === "running").lastIndexOf(true);
                const base: ToolStep =
                  i >= 0 ? (tools[i] as ToolStep) : { id: ++toolSeq.current, name: d.name, status: "running" };
                const next: ToolStep = {
                  ...base,
                  status: d.phase === "end" ? "done" : "error",
                  preview: d.result_preview,
                  durationMs: d.duration_ms,
                  message: d.message,
                };
                if (i >= 0) tools[i] = next;
                else tools.push(next);
              }
              return { ...m, tools, status: m.status === "pending" ? "streaming" : m.status };
            });
            break;
          }
          case "token":
            acc += f.data.text;
            if (flushTimer === undefined) flushTimer = window.setTimeout(flush, 33);
            break;
          case "final":
            window.clearTimeout(flushTimer);
            acc = f.data.answer;
            patch(botId, (m) => ({
              ...m,
              text: f.data.answer,
              status: "done",
              durationMs: performance.now() - started,
            }));
            break;
          case "error":
            window.clearTimeout(flushTimer);
            patch(botId, (m) => ({
              ...m,
              text: acc || m.text,
              status: "error",
              error: { message: f.data.message, code: f.data.code, requestId: f.data.request_id },
            }));
            break;
          default:
            break;
        }
      };

      void (async () => {
        try {
          if (streamTokens) {
            await streamAgent({ session_id: sessionId, message: text }, onFrame, controller.signal);
            // The contract guarantees final|error; recover gracefully if the stream just closed.
            window.clearTimeout(flushTimer);
            patch(botId, (m) =>
              m.status === "pending" || m.status === "streaming"
                ? acc
                  ? { ...m, text: acc, status: "done", durationMs: performance.now() - started }
                  : {
                      ...m,
                      status: "error",
                      error: { message: "The stream ended without an answer.", code: "stream_closed" },
                    }
                : m,
            );
          } else {
            const r = await api.invoke({ session_id: sessionId, message: text }, controller.signal);
            tracer.invoked(r);
            patch(botId, (m) => ({
              ...m,
              text: r.answer,
              status: "done",
              toolsUsed: r.tools_used,
              requestId: r.request_id,
              durationMs: performance.now() - started,
            }));
          }
        } catch (e) {
          window.clearTimeout(flushTimer);
          const aborted = e instanceof DOMException && e.name === "AbortError";
          const d = describeError(e);
          tracer.failure(aborted ? "Stopped by user" : d.message, aborted ? {} : { code: d.code, request_id: d.requestId });
          patch(botId, (m) =>
            aborted
              ? { ...m, text: acc || m.text, status: "stopped" }
              : { ...m, text: acc || m.text, status: "error", error: d },
          );
        } finally {
          if (ctl.current === controller) ctl.current = null;
          setBusy(false);
        }
      })();
    },
    [busy, patch, sessionId, streamTokens],
  );

  const stop = useCallback(() => ctl.current?.abort(), []);

  const newSession = useCallback(() => {
    ctl.current?.abort();
    const id = makeSessionId();
    writeStorage(STORAGE_KEYS.sessionId, id);
    setSessionId(id);
    setMessages([]);
  }, []);

  const value = useMemo<ChatApi>(
    () => ({ messages, sessionId, busy, streamTokens, setStreamTokens, send, stop, newSession }),
    [messages, sessionId, busy, streamTokens, setStreamTokens, send, stop, newSession],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useChat outside ChatProvider");
  return v;
}
