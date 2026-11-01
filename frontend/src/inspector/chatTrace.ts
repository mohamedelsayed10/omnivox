import type { InvokeResponse, StreamFrame } from "../api/types";
import { randomId } from "../lib/format";
import { inspectorStore } from "./store";

/**
 * Maps one text-chat request (the SSE frames of POST /agent/stream) onto the
 * same event shape the voice pipeline emits over the data channel, so the
 * Inspector renders both identically. Each chat message is one "turn".
 *
 * Timestamps are client-side (time the frame was received); `ttft_ms` is
 * measured from the moment the request was sent.
 */
export class ChatTracer {
  private readonly t0 = Date.now();
  private ttftMs: number | undefined;
  private seq = 0;

  constructor(
    private readonly run: number,
    private readonly turn: number,
    private readonly sessionId: string,
  ) {}

  private emit(
    source: string,
    type: string,
    label: string,
    data: Record<string, unknown>,
    duration_ms?: number,
  ): void {
    inspectorStore.ingest(
      {
        v: 1,
        id: `${randomId("chat")}_${++this.seq}`,
        ts: Date.now(),
        turn: this.turn,
        source,
        type,
        label,
        ...(duration_ms != null ? { duration_ms } : {}),
        data,
      },
      this.run,
      "chat",
    );
  }

  userMessage(text: string): void {
    this.emit("session", "user_message", "User message", { text, session_id: this.sessionId });
  }

  frame(f: StreamFrame): void {
    switch (f.event) {
      case "node":
        this.emit(
          "graph",
          f.data.phase === "start" ? "node_start" : "node_end",
          `Node ${f.data.name}`,
          { node: f.data.name },
          f.data.duration_ms,
        );
        break;
      case "tool": {
        const { phase, name, args, result_preview, duration_ms, message } = f.data;
        if (phase === "start") this.emit("tool", "start", `Tool ${name}`, { name, args });
        else if (phase === "end") this.emit("tool", "end", `Tool ${name}`, { name, result_preview }, duration_ms);
        else this.emit("tool", "error", `Tool ${name} failed`, { name, message: message ?? "tool error" }, duration_ms);
        break;
      }
      case "token":
        if (this.ttftMs === undefined) {
          this.ttftMs = Date.now() - this.t0;
          this.emit("llm", "first_token", "First token", { ttft_ms: this.ttftMs, measured: "client" });
        }
        break;
      case "final": {
        const total = Date.now() - this.t0;
        this.emit("session", "final", "Answer complete", {
          session_id: f.data.session_id,
          characters: f.data.answer.length,
        });
        this.emit("latency", "turn_summary", "Turn latency", {
          llm_ttft_ms: this.ttftMs,
          total_ms: total,
          measured: "client",
        });
        break;
      }
      case "error":
        this.emit("error", "error", "Stream error", {
          message: f.data.message,
          source: "agent.stream",
          code: f.data.code,
          request_id: f.data.request_id,
        });
        break;
      default:
        this.emit("session", "unknown_frame", `Unknown SSE frame: ${f.name}`, { event: f.name, data: f.data });
    }
  }

  /** Non-streaming /agent/invoke finished. */
  invoked(r: InvokeResponse): void {
    this.emit("session", "invoke_response", "Answer received", {
      session_id: r.session_id,
      tools_used: r.tools_used,
      request_id: r.request_id,
      characters: r.answer.length,
    });
    this.emit("latency", "turn_summary", "Turn latency", { total_ms: Date.now() - this.t0, measured: "client" });
  }

  /** The request failed before/without a stream (HTTP error, network, abort). */
  failure(message: string, extra: Record<string, unknown> = {}): void {
    this.emit("error", "error", "Request failed", { message, source: "agent.stream", ...extra });
  }
}
