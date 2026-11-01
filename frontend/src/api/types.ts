/**
 * Every request/response shape of the OmniVox backend contract, plus the
 * trace-event envelope used by the Inspector. Keep this file in sync with the
 * backend; nothing else in the frontend should declare wire types.
 */

// ---------------------------------------------------------------- errors

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: unknown;
  };
}

// ---------------------------------------------------------------- health / info

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  env: string;
  uptime_seconds: number;
}

export interface InfoResponse {
  app_name: string;
  version: string;
  llm_model: string;
  stt_provider: string;
  stt_model: string;
  tts_provider: string;
  tts_model: string;
  embedding_model: string;
  turn_detector: string;
  tracing_provider: string;
  auth_required: boolean;
}

// ---------------------------------------------------------------- livekit

export interface TokenRequest {
  identity?: string;
  room?: string;
}

export interface TokenResponse {
  token: string;
  url: string;
  room: string;
  identity: string;
}

// ---------------------------------------------------------------- agent

export interface AgentRequest {
  /** 1..64 characters. */
  session_id: string;
  message: string;
}

export interface InvokeResponse {
  session_id: string;
  answer: string;
  tools_used: string[];
  request_id: string;
}

export type ToolPhase = "start" | "end" | "error";

export interface NodeFrame {
  name: string;
  phase: "start" | "end";
  duration_ms?: number;
}

export interface ToolFrame {
  name: string;
  phase: ToolPhase;
  args?: unknown;
  result_preview?: string;
  duration_ms?: number;
  /** Not in the contract's field list, tolerated on `phase: "error"`. */
  message?: string;
}

export interface TokenFrame {
  text: string;
}

export interface FinalFrame {
  answer: string;
  session_id: string;
}

export interface ErrorFrame {
  code: string;
  message: string;
  request_id: string;
}

/** One parsed SSE frame from POST /api/v1/agent/stream. */
export type StreamFrame =
  | { event: "node"; data: NodeFrame }
  | { event: "tool"; data: ToolFrame }
  | { event: "token"; data: TokenFrame }
  | { event: "final"; data: FinalFrame }
  | { event: "error"; data: ErrorFrame }
  | { event: "unknown"; name: string; data: unknown };

// ---------------------------------------------------------------- knowledge

export interface UploadResponse {
  source: string;
  chunks: number;
  characters: number;
}

export interface KnowledgeDocument {
  source: string;
  chunks: number;
}

export interface ListDocumentsResponse {
  documents: KnowledgeDocument[];
}

export interface DeleteDocumentResponse {
  source: string;
  deleted_chunks: number;
}

export interface SearchRequest {
  query: string;
  top_k?: number;
}

export interface SearchResult {
  source: string;
  chunk_index: number;
  score: number;
  text: string;
}

export interface SearchResponse {
  results: SearchResult[];
}

// ---------------------------------------------------------------- trace events

/** Topic on the LiveKit data channel that carries trace events. */
export const TRACE_TOPIC = "omnivox.trace";

export const KNOWN_SOURCES = [
  "session",
  "vad",
  "stt",
  "eot",
  "graph",
  "tool",
  "llm",
  "tts",
  "latency",
  "error",
] as const;

export type TraceSource = (typeof KNOWN_SOURCES)[number];

/** Wire envelope (v1). `source`/`type` may be anything for forward compatibility. */
export interface TraceEvent {
  v: number;
  id: string;
  /** Milliseconds since the epoch, server clock. */
  ts: number;
  turn: number;
  source: string;
  type: string;
  label: string;
  duration_ms?: number;
  data: Record<string, unknown>;
}

/** Documented `data` payloads, keyed by `source.type`. Unknown pairs are still rendered. */
export interface TraceDataMap {
  "session.agent_state": { state: string };
  "vad.user_state": { state: "speaking" | "listening" | "away" };
  "stt.interim": { text: string };
  "stt.final": { text: string; language?: string };
  "eot.detected": { delay_ms: number; transcript_delay_ms?: number };
  "graph.node_start": { node: string };
  "graph.node_end": { node: string };
  "graph.route": { from: string; to: string };
  "tool.start": { name: string; args: unknown };
  "tool.end": { name: string; result_preview: string };
  "tool.error": { name: string; message: string };
  "llm.start": { model: string };
  "llm.first_token": { ttft_ms: number };
  "llm.end": { input_tokens: number; output_tokens: number; finish_reason: string };
  "tts.start": { characters: number };
  "tts.first_audio": { ttfb_ms: number };
  "tts.end": { audio_ms: number };
  "latency.turn_summary": {
    eot_ms: number;
    llm_ttft_ms: number;
    tts_ttfb_ms: number;
    total_ms: number;
  };
  "error.error": { message: string; source: string };
}

export type TurnSummary = TraceDataMap["latency.turn_summary"];
