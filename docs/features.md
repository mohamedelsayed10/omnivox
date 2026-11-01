# Features, limits and assumptions

## Features

| Feature | Behavior | Where | Proof |
| --- | --- | --- | --- |
| Real-time voice agent | Browser mic through LiveKit: VAD, streaming STT, end-of-turn model, LangGraph agent, streaming TTS, barge-in | `src/voice/`, `src/ai_models/` | `tests/voice/`, `tests/ai_models/test_speech.py` |
| LLM through an OpenAI-compatible API | Gemini by default, any compatible server by `OPENAI_BASE_URL` | `src/ai_models/llm.py` | `tests/ai_models/test_llm.py`, `scripts/smoke_models.py` |
| Web search | `web_search` tool using ddgs, run in a thread with a timeout | `src/graph/tools/web_search.py`, `src/clients/web_search.py` | `tests/graph/test_tools.py`, `tests/clients/test_web_search.py` |
| Retrieval from documents | `knowledge_search` tool: Cohere embeddings and Qdrant; upload, list, delete and search over the API and GUI | `src/rag/`, `src/graph/tools/knowledge_search.py` | `tests/rag/`, `tests/clients/test_qdrant.py`, `tests/api/test_routes.py` |
| Swappable speech models | `STT_PROVIDER` / `TTS_PROVIDER` choose ElevenLabs or any OpenAI-format server | `src/ai_models/asr.py`, `tts.py` | `tests/ai_models/test_speech.py` |
| Inspector | Every step (VAD, STT, end of turn, graph nodes, routing, tool calls, LLM timing, TTS, latency) as typed events over the LiveKit data channel and in the text chat stream | `src/voice/inspector.py`, `src/graph/trace.py` | `tests/voice/test_inspector.py`, `tests/graph/test_trace.py` |
| Text chat | `invoke` and SSE `stream` with per-session memory | `src/api/routes/graph/agent.py`, `src/services/chat_service.py` | `tests/services/test_chat_service.py`, `tests/api/test_routes.py` |
| Web GUI | Voice, text chat, knowledge base and Inspector, see [frontend.md](frontend.md) | `frontend/` | `npm run build` |

## Limits

| Limit | Value | Setting |
| --- | --- | --- |
| User message | 20,000 characters | `MAX_INPUT_CHARS` |
| Request body | 12 MB | `MAX_BODY_BYTES` |
| Uploaded document | 5 MB, `.txt` `.md` `.pdf` | `RAG_MAX_UPLOAD_BYTES` |
| Concurrent text chat runs | 8 | `MAX_CONCURRENT_RUNS` |
| Graph steps per turn | 25 | `GRAPH_RECURSION_LIMIT` |
| History sent to the model | last 40 messages | `GRAPH_MAX_HISTORY_MESSAGES` |
| Web search | 5 results, 10 s | `WEB_SEARCH_MAX_RESULTS`, `WEB_SEARCH_TIMEOUT` |
| Chunk | 800 characters, 100 overlap, top 4 | `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_TOP_K` |

## Assumptions

- **LiveKit runs locally in Docker** with development credentials; LiveKit Cloud works by changing `LIVEKIT_URL`, `LIVEKIT_PUBLIC_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`.
- **"OpenAI format" for speech** means a provider switch. ElevenLabs offers no OpenAI-format TTS/STT endpoint, so the `elevenlabs` provider uses its native streaming API and the `openai` provider targets any server that does speak the OpenAI audio API (vLLM and similar).
- **End of turn** uses LiveKit's local audio model (`v1-mini`) so no cloud service is involved.
- `eleven_v4_turbo` and `scribe_v2_realtime` are used as named in the ElevenLabs documentation; the LiveKit plugin docs do not list `eleven_v4_turbo`, and the model name is passed through unchanged.
- **Voice memory** is LiveKit's chat context for the length of the call; the checkpointer backs the text chat only.
- Any one `session_id` is one conversation; there are no user accounts. `API_KEYS` is a shared secret, not per-user auth.
- The knowledge base is one shared collection; there is no per-user separation.
- **License** is MIT.

## Deviations from the project template

- `TRACING_PROVIDER` is `none` or `langsmith`; Langfuse is left out because only a LangSmith key exists.
- `GRAPH_MEMORY_BACKEND` is `memory` or `sqlite`; postgres and redis would be unused code.
- No structured-output method on `LLMService`: nothing in this service needs one.
- `src/rag/` and `src/voice/` are extra modules. `src/rag/` sits between `clients/`/`ai_models/` and `services/`/`graph/`. `src/voice/` is a second composition root next to `src/app.py`; shared wiring lives in `src/composition.py`.
- Graph tools call the `Retriever` (in `src/rag/`) rather than `clients/` directly, because retrieval is embed-then-search.
- The model layer is `src/ai_models/` (several model types) instead of the single-model layout in the template.
- Extra error row: `service_not_configured` (503) and `not_found` (404) for features and items that do not exist.
- STT and TTS timing is traced through LiveKit's per-reply metrics (`voice.turn` runs), because the plugins are driven by the voice session rather than called from our code.

## Known limitations

- The end-to-end voice path needs a valid ElevenLabs API key (`sk_...`). With the `openai` provider and any OpenAI-format audio server it runs without ElevenLabs.
- Google's free Gemini tier allows about 20 requests per day for `gemini-3-flash`. A voice turn that uses a tool costs two requests, so use a paid key for real use. Quota errors surface as `llm_rate_limited` (429) in the API and as a spoken apology in a call.
- Web search depends on public DuckDuckGo-style endpoints and can be slow (about 3 seconds) or rate limited.
- Windows: `make` is not installed by default (see [installation.md](installation.md)); systemd and nginx targets are for Linux.
