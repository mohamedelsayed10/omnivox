# Models, retries and tracing

All model clients are built in `src/ai_models/` and nowhere else. Every wrapper derives from `AIModel` (`base.py`), which gives it an `info` description (no secrets) and a `traced()` helper that logs latency.

| Module | Class | Model type | Backed by |
| --- | --- | --- | --- |
| `llm.py` | `LLMService` | chat | `langchain-openai` `ChatOpenAI` on any OpenAI-compatible endpoint |
| `embeddings.py` | `EmbeddingService` | embeddings | `OpenAIEmbeddings` (default Cohere `embed-v5.0-fast`) |
| `asr.py` | `SpeechToText` | STT | LiveKit plugins: ElevenLabs, or `openai` format via `STT_BASE_URL` |
| `tts.py` | `TextToSpeech` | TTS | LiveKit plugins: ElevenLabs, or `openai` format via `TTS_BASE_URL` |
| `vad.py` | `VoiceActivityDetector` | VAD | Silero, local |
| `turn.py` | `TurnDetection` | end of turn | LiveKit audio model `v1-mini`, local; builds the session's turn options |

## LLM service

- Defaults: `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `OPENAI_MODEL=gemini-3-flash-preview`. Any OpenAI-compatible server works (vLLM, OpenAI, Ollama); the model must support tool calling.
- Methods: `get_model()` for code that binds tools itself, `ainvoke(messages, tools=..., config=...)` returning a validated `AIMessage`, and `astream(messages)` yielding text.
- Retries and timeout: the client's own `max_retries=MAX_RETRIES` and `timeout=REQUEST_TIMEOUT`; there is no second retry layer.
- Errors: timeouts become `LLMTimeoutError` (504), rate limits `LLMRateLimitError` (429), everything else `LLMError` (502). Empty output, a provider content-filter block and an empty stream are `LLMError`. Output cut by the token limit but non-empty is returned with a warning. User messages longer than `MAX_INPUT_CHARS` are rejected with `InvalidInputError` before any call.
- Latency and token usage are logged per call. `OPENAI_REASONING_EFFORT=minimal` keeps Gemini's thinking short, which matters for voice.
- Structured output is not exposed: nothing in the graph needs it.

### Thinking on or off (open-source models)

Qwen, Gemma, Nemotron and other open-source models served by vLLM or OpenRouter think before answering, which adds seconds to the first spoken word. One setting controls it:

```dotenv
OPENAI_BASE_URL=https://openrouter.ai/api/v1/
OPENAI_MODEL=nvidia/nemotron-3.5-lightning:free
OPENAI_REASONING_EFFORT=
OPENAI_ENABLE_THINKING=false
```

`OPENAI_ENABLE_THINKING` is sent to the endpoint as `extra_body={"chat_template_kwargs": {"enable_thinking": <value>}}` (the OpenAI SDK merges `extra_body` into the request). On `openrouter.ai` the body also carries `reasoning: {"enabled": <value>}`, because OpenRouter ignores `chat_template_kwargs` for some models, Nemotron among them. `false` turns thinking off, `true` turns it on, and blank sends nothing so the model default applies. Gemini models use `OPENAI_REASONING_EFFORT` instead; for other hosts leave that blank, because it is a Gemini-style parameter. The current value is shown in the Inspector's `session.connected` event (`models.llm.thinking`).

Models without a `chat_template_kwargs` convention simply ignore the field. If a provider rejects it with HTTP 400, leave `OPENAI_ENABLE_THINKING` blank.

### Measured: `nvidia/nemotron-3.5-lightning:free` on OpenRouter

Tested through the Docker stack with the recorded question "How long does the free trial last in my documents?", which needs `knowledge_search`, over a scripted LiveKit call (ElevenLabs speech models):

| Setting | Time to first token | Called the tool |
| --- | --- | --- |
| `OPENAI_ENABLE_THINKING=false` | about 0.5 s | about half of the runs; otherwise it said "Let me check" and ended the turn, or guessed |
| blank (model default) | 4 to 11 s (300 to 870 reasoning tokens) | every run |
| blank with `OPENAI_REASONING_EFFORT=low` | 7 to 14 s | every run, and no faster: the effort level does not shorten this model's reasoning |

Text chat through the API called its tools correctly every time it was tried. For voice, the default stays `false` (the first spoken word matters most); the cost is that this free model sometimes skips a tool. If that matters, use a model with reliable tool calling or accept the slow first token. Prompt version 1.1 ([prompts.md](prompts.md)) improved the rate a little but does not remove the behaviour.

### Gemini 3 tool calls

Gemini 3 returns a `thought_signature` with every tool call and answers HTTP 400 when a replayed tool call lacks it. `langchain-openai` drops that field, so a second step after a tool result would fail. `GeminiChatOpenAI` (used automatically for `generativelanguage.googleapis.com` URLs) remembers each signature from the stream by tool call id and puts it back into the next request; for an unknown id (for example after a restart) it sends Google's documented `skip_thought_signature_validator` value. Other providers use plain `ChatOpenAI`.

## Embeddings

`EmbeddingService` embeds in batches of `EMBEDDING_BATCH_SIZE` (Cohere accepts at most 96), at most `EMBEDDING_CONCURRENCY` requests at a time, and keeps order. The vector size is found by embedding a probe text once (the Cohere compatibility endpoint does not accept `dimensions`; `embed-v5.0-fast` returns 2048 by default), so the Qdrant collection is created with the right size and nothing is hard-coded. A collection created with a different size is refused with a clear message. Failures become `ExternalServiceError`; a missing key becomes `ConfigurationError` only when the knowledge base is used.

Each `LLMService` and `EmbeddingService` creates its own HTTP client and closes it in `Runtime.aclose()`. `langchain-openai` otherwise shares one cached client per base URL, and with the voice worker (every call runs on its own event loop) the second call fails with "Event loop is closed".

Documents and queries must use the same model family. Changing `EMBEDDING_MODEL` needs a new `QDRANT_COLLECTION` (or deleting the old one).

## Speech models

`STT_PROVIDER` and `TTS_PROVIDER` choose between the native ElevenLabs streaming plugins and the OpenAI-format plugins. ElevenLabs does not expose OpenAI-format audio endpoints itself; the `openai` provider is for self-hosted or third-party servers (vLLM and similar), so moving off ElevenLabs is an `.env` change. A blank key for those servers is replaced by a placeholder, because the OpenAI client refuses an empty one.

`ELEVENLABS_API_KEY` must be an API key (it starts with `sk_`). ElevenLabs rejects a key *id* with `api_key_id_used_as_api_key`. A 402 `paid_plan_required` from TTS means the voice in `TTS_VOICE` is a library voice that your plan cannot use through the API; pick another voice id (the default, Sarah, works on free plans). `eleven_v4_turbo` and `scribe_v2_realtime` were confirmed to work with the plugin.

## Tracing

`TRACING_PROVIDER` is `none` or `langsmith`.

1. Set `TRACING_PROVIDER=langsmith`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT`.
2. `Tracing.get_callbacks()` returns a `LangChainTracer`; `build_run_config` (`src/graph/trace.py`) puts it in the `RunnableConfig` with the `thread_id`, tags (`omnivox`, `text` or `voice`) and metadata (`request_id`, `service`, `session_id`) of every graph run.
3. The voice worker also records each reply's latency summary as a `voice.turn` run.
4. Tracing errors are logged and swallowed; `Tracing.flush()` runs on shutdown.

With `none`, `get_callbacks()` returns an empty list and nothing leaves the process.
