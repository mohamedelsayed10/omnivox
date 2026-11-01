import { readStorage, STORAGE_KEYS } from "../lib/storage";
import type {
  AgentRequest,
  ApiErrorBody,
  DeleteDocumentResponse,
  HealthResponse,
  InfoResponse,
  InvokeResponse,
  ListDocumentsResponse,
  SearchRequest,
  SearchResponse,
  StreamFrame,
  TokenRequest,
  TokenResponse,
  UploadResponse,
} from "./types";

/** A failed API call. `requestId` comes from the error body or the X-Request-ID header. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details?: unknown;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    requestId?: string;
    details?: unknown;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId;
    this.details = init.details;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Normalise anything thrown into `{message, code?, requestId?}` for the UI. */
export function describeError(e: unknown): { message: string; code?: string; requestId?: string } {
  if (isApiError(e)) return { message: e.message, code: e.code, requestId: e.requestId };
  if (e instanceof DOMException && e.name === "AbortError") return { message: "Request cancelled." };
  if (e instanceof Error) return { message: e.message };
  return { message: String(e) };
}

function headers(extra?: Record<string, string>): Headers {
  const h = new Headers(extra);
  const key = readStorage(STORAGE_KEYS.apiKey)?.trim();
  if (key) h.set("X-API-Key", key);
  if (!h.has("Accept")) h.set("Accept", "application/json");
  return h;
}

async function toApiError(res: Response): Promise<ApiError> {
  const headerId = res.headers.get("X-Request-ID") ?? undefined;
  let body: unknown;
  const text = await res.text().catch(() => "");
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = undefined;
  }
  const err = (body as Partial<ApiErrorBody> | undefined)?.error;
  if (err && typeof err.message === "string") {
    return new ApiError({
      status: res.status,
      code: err.code ?? "error",
      message: err.message,
      requestId: err.request_id || headerId,
      details: err.details,
    });
  }
  // Not our error envelope: a proxy failure, an HTML page, FastAPI's default {"detail"}, etc.
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  const proxyDown = res.status === 502 || res.status === 503 || res.status === 504 || (res.status === 500 && !text);
  const message = proxyDown
    ? "The API is unreachable. Is the backend running?"
    : typeof detail === "string"
      ? `${detail} (HTTP ${res.status})`
      : `Request failed with HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}.`;
  return new ApiError({
    status: res.status,
    code: proxyDown ? "unreachable" : "http_error",
    message,
    requestId: headerId,
    details: detail ?? (text && text.length < 500 ? text : undefined),
  });
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Could not reach the API. Check that the backend is running and your network is up.",
    });
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, { ...init, headers: headers(init.headers as Record<string, string> | undefined) });
  return (await res.json()) as T;
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return json<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

/** Status polling must not hang forever on a black-holed backend. */
function withTimeout(signal: AbortSignal | undefined, ms = 8000): AbortSignal {
  const timeout = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

// ------------------------------------------------------------------ endpoints

export const api = {
  /** A 200 means up even if the body is empty or not the documented JSON (e.g. during backend bring-up). */
  health: async (signal?: AbortSignal): Promise<HealthResponse> => {
    const res = await send("/health", { headers: headers(), signal: withTimeout(signal) });
    const body: unknown = await res.json().catch(() => undefined);
    const h = (typeof body === "object" && body !== null ? body : {}) as Partial<HealthResponse>;
    return {
      status: "ok",
      service: h.service ?? "",
      version: h.version ?? "",
      env: h.env ?? "",
      uptime_seconds: typeof h.uptime_seconds === "number" ? h.uptime_seconds : Number.NaN,
    };
  },
  info: (signal?: AbortSignal) => json<InfoResponse>("/api/v1/info", { signal: withTimeout(signal) }),

  livekitToken: (body: TokenRequest = {}, signal?: AbortSignal) =>
    post<TokenResponse>("/api/v1/livekit/token", body, signal),

  invoke: (body: AgentRequest, signal?: AbortSignal) => post<InvokeResponse>("/api/v1/agent/invoke", body, signal),

  listDocuments: (signal?: AbortSignal) => json<ListDocumentsResponse>("/api/v1/knowledge/documents", { signal }),

  uploadDocument: (file: File, source?: string, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("file", file);
    if (source?.trim()) form.append("source", source.trim());
    // No Content-Type: the browser adds the multipart boundary.
    return json<UploadResponse>("/api/v1/knowledge/documents", { method: "POST", body: form, signal });
  },

  deleteDocument: (source: string, signal?: AbortSignal) =>
    json<DeleteDocumentResponse>(`/api/v1/knowledge/documents/${encodeURIComponent(source)}`, {
      method: "DELETE",
      signal,
    }),

  search: (body: SearchRequest, signal?: AbortSignal) => post<SearchResponse>("/api/v1/knowledge/search", body, signal),
};

// ------------------------------------------------------------------ SSE

/**
 * Incremental parser for `text/event-stream`. Feed it decoded text chunks; it
 * returns the complete frames found so far and keeps the remainder buffered.
 */
export class SseParser {
  private buffer = "";

  push(chunk: string): StreamFrame[] {
    this.buffer += chunk;
    const frames: StreamFrame[] = [];
    // Frames are separated by a blank line (LF, CRLF or CR).
    const parts = this.buffer.split(/\r\n\r\n|\n\n|\r\r/);
    this.buffer = parts.pop() ?? "";
    for (const part of parts) {
      const frame = parseFrame(part);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  /** Flush a trailing frame that was not terminated by a blank line. */
  end(): StreamFrame[] {
    const rest = this.buffer;
    this.buffer = "";
    const frame = rest.trim() ? parseFrame(rest) : null;
    return frame ? [frame] : [];
  }
}

function parseFrame(raw: string): StreamFrame | null {
  let name = "message";
  const data: string[] = [];
  for (const line of raw.split(/\r\n|\n|\r/)) {
    if (!line || line.startsWith(":")) continue; // blank / comment (keep-alive)
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    let value = i === -1 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length && name === "message") return null;
  const text = data.join("\n");
  let parsed: unknown = text;
  try {
    parsed = JSON.parse(text);
  } catch {
    /* leave as string */
  }
  switch (name) {
    case "node":
    case "tool":
    case "token":
    case "final":
    case "error":
      return { event: name, data: parsed } as StreamFrame;
    default:
      return { event: "unknown", name, data: parsed };
  }
}

/**
 * POST /api/v1/agent/stream and invoke `onFrame` for each SSE frame as it
 * arrives. Resolves when the stream closes; rejects with ApiError (HTTP errors
 * before the stream starts) or AbortError. POST needs a body, hence fetch +
 * ReadableStream rather than EventSource.
 */
export async function streamAgent(
  body: AgentRequest,
  onFrame: (frame: StreamFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await send("/api/v1/agent/stream", {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.body) {
    throw new ApiError({
      status: res.status,
      code: "no_stream",
      message: "The browser did not expose a response stream.",
      requestId: res.headers.get("X-Request-ID") ?? undefined,
    });
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const f of parser.push(decoder.decode(value, { stream: true }))) onFrame(f);
    }
    for (const f of parser.push(decoder.decode())) onFrame(f);
    for (const f of parser.end()) onFrame(f);
  } finally {
    reader.releaseLock();
  }
}
