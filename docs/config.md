# Configuration

Every setting is an environment variable read by `config/settings.py` (Pydantic Settings). Copy `.env.example` to `.env` (`make env`) and fill in the secrets. A blank value means "unset" and the default applies. The same file works for the app, Docker Compose (`env_file`) and systemd (`EnvironmentFile`), so it contains plain `KEY=VALUE` lines only.

Missing required values stop the app at startup with a message naming each one. `tests/config/test_settings.py` fails when `.env.example`, `Settings` and this page disagree.

Secrets are held as `SecretStr`, never printed, and masked in logs.

## App

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `APP_NAME` | string | `omnivox` | Service name, also used by the Makefile for systemd and nginx names. |
| `APP_ENV` | `development` \| `production` | `development` | development or production |
| `HOST` | string | `0.0.0.0` | Address the API binds to. |
| `PORT` | integer | `8100` | API port. 8100 avoids the common clash with other tools on 8000. |
| `API_PREFIX` | string | `/api/v1` | URL prefix of the feature routes (/health stays at the root). |
| `ROOT_PATH` | string | unset | Set to /omnivox when nginx serves the API under a path prefix. |
| `CORS_ORIGINS` | string | `http://localhost:5173` | Comma separated browser origins allowed to call the API. |
| `API_KEYS` | secret | empty | Comma separated API keys checked in the X-API-Key header. Empty disables auth. |
| `RELOAD` | boolean | `False` | Reload on code changes (development only). |
| `MAX_BODY_BYTES` | integer | `12582912` | Largest accepted request body in bytes (must exceed RAG_MAX_UPLOAD_BYTES). |
| `MAX_CONCURRENT_RUNS` | integer | `8` | Maximum concurrent agent runs handled by the text chat endpoints. |

## LLM (any OpenAI compatible endpoint, default Gemini)

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | secret | **required** | Key for the LLM endpoint (a Gemini key for the default base URL). Required. |
| `OPENAI_BASE_URL` | string | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI compatible base URL. Change it to use another provider or a vLLM server. |
| `OPENAI_MODEL` | string | `gemini-3-flash-preview` | Chat model name. It must support tool calling. |
| `OPENAI_TEMPERATURE` | number | `1.0` | Sampling temperature. Gemini 3 works best at its default of 1.0. |
| `OPENAI_MAX_TOKENS` | integer (optional) | unset | Cap on reply tokens. Blank means no cap. |
| `OPENAI_REASONING_EFFORT` | `minimal` \| `low` \| `medium` \| `high` (optional) | unset | minimal, low, medium or high. Lower is faster for voice. Blank uses the model default. |
| `OPENAI_ENABLE_THINKING` | boolean (optional) | unset | Thinking for open-source and reasoning models (Qwen, Gemma, Nemotron on vLLM or OpenRouter). Sent as chat_template_kwargs.enable_thinking, plus OpenRouter's reasoning.enabled on openrouter.ai. false turns thinking off (faster replies), true turns it on, blank sends nothing and the model default applies. |
| `MAX_RETRIES` | integer | `3` | Retries inside the model clients for transient errors. |
| `REQUEST_TIMEOUT` | number | `60.0` | Seconds before a model call times out. |
| `MAX_INPUT_CHARS` | integer | `20000` | Longest user message accepted, in characters. |

## Embeddings (OpenAI compatible, default Cohere)

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `EMBEDDING_BASE_URL` | string | `https://api.cohere.ai/compatibility/v1` | OpenAI compatible embeddings endpoint. |
| `EMBEDDING_MODEL` | string | `embed-v5.0-fast` | Embedding model name. Documents and queries must use the same family. |
| `EMBEDDING_API_KEY` | secret (optional) | unset | Key for the embeddings endpoint (Cohere). Without it the knowledge base is unavailable. |
| `EMBEDDING_BATCH_SIZE` | integer | `96` | Texts per embedding request (Cohere accepts at most 96). |
| `EMBEDDING_CONCURRENCY` | integer | `4` | Embedding requests in flight at once. |

## Speech to text

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `ELEVENLABS_API_KEY` | secret (optional) | unset | ElevenLabs API key (starts with sk_, not the key id). Needed when STT or TTS uses elevenlabs. |
| `STT_PROVIDER` | `elevenlabs` \| `openai` | `elevenlabs` | elevenlabs (native streaming) or openai (any /v1/audio/transcriptions server, for example vLLM). |
| `STT_MODEL` | string | `scribe_v2_realtime` | Speech to text model name. |
| `STT_LANGUAGE` | string (optional) | unset | Language code such as en or ar. Blank means automatic detection where supported. |
| `STT_BASE_URL` | string (optional) | unset | Only for STT_PROVIDER=openai, for example http://localhost:8001/v1 |
| `STT_API_KEY` | secret (optional) | unset | Key for that server. Blank is fine for servers without auth. |

## Text to speech

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `TTS_PROVIDER` | `elevenlabs` \| `openai` | `elevenlabs` | elevenlabs (native streaming) or openai (any /v1/audio/speech server, for example vLLM). |
| `TTS_MODEL` | string | `eleven_v4_turbo` | Text to speech model name. |
| `TTS_VOICE` | string | `EXAVITQu4vr4xnSDxMaL` | ElevenLabs voice id (default: Sarah), or the voice name for an OpenAI compatible server. Free ElevenLabs plans cannot use library voices through the API; Sarah, Roger, George and Charlie work. |
| `TTS_BASE_URL` | string (optional) | unset | Only for TTS_PROVIDER=openai, for example http://localhost:8002/v1 |
| `TTS_API_KEY` | secret (optional) | unset | Key for that server. Blank is fine for servers without auth. |

## Voice pipeline

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `VAD_ACTIVATION_THRESHOLD` | number | `0.5` | Silero VAD: speech probability above this value counts as speech. |
| `VAD_MIN_SPEECH_DURATION` | number | `0.05` | Seconds of speech needed before VAD reports speech. |
| `VAD_MIN_SILENCE_DURATION` | number | `0.55` | Seconds of silence before VAD reports the end of speech. |
| `TURN_DETECTOR` | `audio` \| `vad` \| `stt` | `audio` | End of turn detection: audio (local LiveKit model), vad (silence only) or stt (STT endpointing). |
| `MIN_ENDPOINTING_DELAY` | number | `0.5` | Shortest wait after speech ends before the reply starts, in seconds. |
| `MAX_ENDPOINTING_DELAY` | number | `3.0` | Longest wait when the turn detector expects the user to keep talking, in seconds. |
| `ALLOW_INTERRUPTIONS` | boolean | `True` | Let the user talk over the agent. |
| `PREEMPTIVE_GENERATION` | boolean | `False` | Start the LLM before the turn is confirmed. Faster but may repeat tool calls. |
| `AGENT_GREETING` | string | `Hi, this is OmniVox. Ask me anything, or ask about your documents.` | Spoken when a caller joins. |
| `INSPECTOR_ENABLED` | boolean | `True` | Publish internal steps to the GUI Inspector over the LiveKit data channel. |
| `INSPECTOR_MAX_FIELD_CHARS` | integer | `1500` | Longest text value inside an Inspector event. |

## LiveKit

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `WORKER_IDLE_PROCESSES` | integer | `1` | Pre-started job processes of the agent worker. |
| `WORKER_PORT` | integer | `8181` | Port of the worker health endpoint (0 picks a free port). |
| `LIVEKIT_URL` | string | `ws://localhost:7880` | Server address used by the API and the agent worker. |
| `LIVEKIT_PUBLIC_URL` | string | `ws://localhost:7880` | Server address handed to the browser. |
| `LIVEKIT_API_KEY` | string | `devkey` | Development defaults match the local Docker server started by docker compose. |
| `LIVEKIT_API_SECRET` | secret | **required** | Secret of LIVEKIT_API_KEY. Required. Change both before exposing the server. |
| `LIVEKIT_TOKEN_TTL_SECONDS` | integer | `3600` | Lifetime of browser join tokens, in seconds. |

## Knowledge base (Qdrant)

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `QDRANT_URL` | string | `http://localhost:6333/` | Qdrant address. Use :memory: for a throwaway in-process store. |
| `QDRANT_API_KEY` | secret (optional) | unset | Qdrant API key. Blank for none. |
| `QDRANT_COLLECTION` | string | `omnivox_knowledge` | Collection that holds the document chunks. |
| `RAG_CHUNK_SIZE` | integer | `800` | Characters per chunk. |
| `RAG_CHUNK_OVERLAP` | integer | `100` | Characters repeated between neighbouring chunks. |
| `RAG_TOP_K` | integer | `4` | Passages returned per search. |
| `RAG_SCORE_THRESHOLD` | number | `0.0` | Drop passages scoring below this cosine similarity. 0 keeps everything. With embed-v5.0-fast, matching passages scored about 0.27 to 0.47 and unrelated text 0.13 to 0.19, so 0.2 filters noise. |
| `RAG_MAX_UPLOAD_BYTES` | integer | `5000000` | Largest uploaded document, in bytes. |

## Web search (ddgs)

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `WEB_SEARCH_MAX_RESULTS` | integer | `5` | Results handed to the model per search. |
| `WEB_SEARCH_TIMEOUT` | number | `10.0` | Seconds before a web search is abandoned. |
| `WEB_SEARCH_REGION` | string | `us-en` | Region code such as us-en, uk-en or wt-wt (no region; some engines fail with it). |

## Logging

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | DEBUG, INFO, WARNING, ERROR or CRITICAL. |
| `LOG_FORMAT` | `console` \| `json` | `console` | console or json |
| `LOG_DIR` | string | `files/logs` | Directory of the rotating log file (created if missing). |
| `LOG_MAX_BYTES` | integer | `10485760` | Size at which the log file rotates. |
| `LOG_BACKUP_COUNT` | integer | `5` | Rotated log files kept. |

## Tracing

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `TRACING_PROVIDER` | `none` \| `langsmith` | `none` | none or langsmith |
| `LANGSMITH_API_KEY` | secret (optional) | unset | LangSmith key, required when TRACING_PROVIDER=langsmith. |
| `LANGSMITH_PROJECT` | string (optional) | unset | LangSmith project that receives the runs. |

## Agent graph

| Variable | Type | Default | Meaning |
| --- | --- | --- | --- |
| `GRAPH_RECURSION_LIMIT` | integer | `25` | Maximum graph steps per turn. Stops runaway tool loops. |
| `GRAPH_MEMORY_BACKEND` | `memory` \| `sqlite` | `memory` | memory or sqlite. Backs the text chat endpoints; voice history lives in LiveKit. |
| `GRAPH_MEMORY_URL` | string | `files/graph_memory.sqlite` | SQLite file path when GRAPH_MEMORY_BACKEND=sqlite. |
| `GRAPH_MAX_HISTORY_MESSAGES` | integer | `40` | Messages kept in the model context per call. |

## Docker Compose only

Read by `deployment/docker-compose.yml`, not by the app. They are commented out in `.env.example`; uncomment one in `.env` to override its default.

| Variable | Default | Meaning |
| --- | --- | --- |
| `QDRANT_HOST_PORT` | `6333` | Host port of the bundled Qdrant container (bound to `127.0.0.1`). Change it when 6333 is already taken. |
| `QDRANT_DOCKER_URL` | `http://qdrant:6333/` | Qdrant address the containers use. Set it to `http://host.docker.internal:6333/` to use a Qdrant running on this machine instead of the bundled one. |
| `LIVEKIT_NODE_IP` | `127.0.0.1` | Address LiveKit advertises for media. Use the host LAN or public IP when browsers connect from other machines. |
| `FRONTEND_PORT` | `8080` | Host port of the web GUI container. |
