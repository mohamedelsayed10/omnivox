# API

Base URL `http://localhost:8100` (set `PORT`). Feature routes live under `API_PREFIX` (`/api/v1`); `/health` is at the root. Interactive docs are at `/docs`. A Postman v2.1 collection is in [api_integration/collections/collection.json](api_integration/collections/collection.json) and request schemas are in [api_integration/schemas](api_integration/schemas/request_schema.json) (update them when a request model changes).

## Authentication

Set `API_KEYS` (comma separated) and send one of them as `X-API-Key`. An empty `API_KEYS` disables authentication. Keys are compared with `secrets.compare_digest`. `/health` never needs a key.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness: status, service, version, env, uptime. No external calls. |
| GET | `/api/v1/info` | Models and switches in use. No secrets. |
| POST | `/api/v1/livekit/token` | Join token for the browser. A new room makes LiveKit dispatch the voice agent. |
| POST | `/api/v1/agent/invoke` | One chat turn through the graph, JSON answer. |
| POST | `/api/v1/agent/stream` | Same turn as server-sent events. |
| POST | `/api/v1/knowledge/documents` | Upload and index a `.txt`, `.md` or `.pdf` file (multipart). |
| GET | `/api/v1/knowledge/documents` | List indexed documents. |
| DELETE | `/api/v1/knowledge/documents/{source}` | Delete a document and its chunks. |
| POST | `/api/v1/knowledge/search` | Passages closest to a query. |

### `GET /health`

```json
{"status": "ok", "service": "omnivox", "version": "0.1.0", "env": "development", "uptime_seconds": 12.4}
```

### `GET /api/v1/info`

```json
{
  "app_name": "omnivox", "version": "0.1.0",
  "llm_model": "gemini-3-flash-preview",
  "stt_provider": "elevenlabs", "stt_model": "scribe_v2_realtime",
  "tts_provider": "elevenlabs", "tts_model": "eleven_v4_turbo",
  "embedding_model": "embed-v5.0-fast",
  "turn_detector": "audio", "tracing_provider": "none",
  "auth_required": false, "knowledge_base_configured": true
}
```

### `POST /api/v1/livekit/token`

Request `{"identity": "alice", "room": "optional-room"}`. Both fields are optional (1 to 64 characters, letters, digits and `._:-`); missing values are generated. Response:

```json
{"token": "<jwt>", "url": "ws://localhost:7880", "room": "omnivox-3fa9c2d1", "identity": "alice"}
```

`url` is `LIVEKIT_PUBLIC_URL`. The token grants join, publish, subscribe and data for that room only and expires after `LIVEKIT_TOKEN_TTL_SECONDS`.

### `POST /api/v1/agent/invoke`

```json
{"session_id": "demo", "message": "What is the capital of France?"}
```

```json
{"session_id": "demo", "answer": "Paris.", "tools_used": [], "request_id": "7a3a6bc8..."}
```

`session_id` (1 to 64 characters) is the memory key: later messages with the same id see earlier ones (`GRAPH_MEMORY_BACKEND`). `message` is limited to `MAX_INPUT_CHARS`.

### `POST /api/v1/agent/stream`

Same body. The response is `text/event-stream` with `Cache-Control: no-cache` and `X-Accel-Buffering: no`. Each frame is `event: <name>` and `data: <json>`:

| Event | Data |
| --- | --- |
| `node` | `{"name": "agent", "phase": "start"}` or `{"name": "agent", "phase": "end", "duration_ms": 825.5}` |
| `tool` | `{"name": "web_search", "phase": "start", "args": {"query": "..."}}`, then `phase` `end` with `result_preview` and `duration_ms`, or `error` |
| `token` | `{"text": "..."}` piece of the reply |
| `final` | `{"answer": "...", "session_id": "demo"}` |
| `error` | `{"code": "llm_error", "message": "...", "request_id": "..."}` |

The stream always ends with exactly one `final` or `error`. Once the headers are sent, failures arrive as an `error` event (the HTTP status stays 200). Closing the connection cancels the run.

### Knowledge base

- Upload: multipart field `file` (`.txt`, `.md`, `.pdf`, up to `RAG_MAX_UPLOAD_BYTES`) and optional text field `source` (document name, default the file name). Uploading an existing name replaces it. Response `{"source": "pricing.md", "chunks": 3, "characters": 2210}`.
- List: `{"documents": [{"source": "pricing.md", "chunks": 3}]}`.
- Search: body `{"query": "...", "top_k": 4}` gives `{"results": [{"source", "chunk_index", "score", "text"}]}`.
- Delete: `{"source": "pricing.md", "deleted_chunks": 3}`; 404 when the name is unknown.

The knowledge base needs `EMBEDDING_API_KEY`; without it these routes (and the agent's `knowledge_search` tool) report that it is not configured.

## Errors

Every failure has the same body and an `X-Request-ID` header with the same id:

```json
{"error": {"code": "llm_timeout", "message": "The language model timed out.", "request_id": "7a3a6bc8...", "details": null}}
```

`details` is only present for validation errors (a list of `{loc, msg, type}`; submitted values are never echoed). Messages are generic: prompts, keys, stack traces and provider payloads are written to the log with the request id, never returned.

| Case | HTTP | `error.code` |
| --- | --- | --- |
| Request validation | 422 | `validation_error` |
| Invalid input (business rule) | 400 | `invalid_input` |
| Missing or wrong API key | 401 | `unauthorized` |
| Unknown document or route | 404 | `not_found` |
| Method not allowed | 405 | `method_not_allowed` |
| Body larger than `MAX_BODY_BYTES` | 413 | `payload_too_large` |
| LLM rate limit | 429 | `llm_rate_limited` |
| LLM failure or unusable output | 502 | `llm_error` |
| External service failure (Qdrant, embeddings, web search) | 502 | `external_service_error` |
| Feature not configured (for example no embedding key) | 503 | `service_not_configured` |
| LLM timeout | 504 | `llm_timeout` |
| Graph failure or step limit | 500 | `graph_error` |
| Anything else | 500 | `internal_error` |

`tests/api/test_errors.py` covers every row.
