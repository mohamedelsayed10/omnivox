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

Qwen, Gemma, Nemotron and other open-source models served by vLLM or OpenRouter think before answering, which adds seconds to the first spoken word. Two settings control it. `OPENAI_ENABLE_THINKING` is the switch, and `OPENAI_THINKING_MODELS` (default `qwen,gemma`) names the models that receive it: the switch is sent only when `OPENAI_MODEL` contains one of those fragments, compared case-insensitively. Any other model, Gemini for example, never gets the parameter, even when the switch is set (the startup log says it was ignored, and the Inspector shows `thinking` as null). For Nemotron, as measured below, add its name to the list:

```dotenv
OPENAI_BASE_URL=https://openrouter.ai/api/v1/
OPENAI_MODEL=nvidia/nemotron-3.5-lightning:free
OPENAI_REASONING_EFFORT=
OPENAI_ENABLE_THINKING=false
OPENAI_THINKING_MODELS=qwen,gemma,nemotron
```

`OPENAI_THINKING_MODELS=*` sends the switch to every model, which was the behavior before the list existed.

`OPENAI_ENABLE_THINKING` is sent to the endpoint as `extra_body={"chat_template_kwargs": {"enable_thinking": <value>}}` (the OpenAI SDK merges `extra_body` into the request). On `openrouter.ai` the body also carries `reasoning: {"enabled": <value>}`, because OpenRouter ignores `chat_template_kwargs` for some models, Nemotron among them. `false` turns thinking off, `true` turns it on, and blank sends nothing so the model default applies. Gemini models use `OPENAI_REASONING_EFFORT` instead; for other hosts leave that blank, because it is a Gemini-style parameter. The value actually sent is shown in the Inspector's `session.connected` event (`models.llm.thinking`).

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

### Self-hosted vLLM on the LAN

Tested with four vLLM servers (LLM `Qwen/Qwen3.5-4B`, embeddings `Qwen/Qwen3-Embedding-0.6B`, STT `CohereLabs/cohere-transcribe-arabic-07-2026`, TTS `bosonai/higgs-audio-v3-tts-4b` on vLLM-Omni):

```dotenv
OPENAI_BASE_URL=http://<llm-host>:8000/v1
OPENAI_MODEL=Qwen/Qwen3.5-4B
OPENAI_ENABLE_THINKING=false
STT_PROVIDER=openai
STT_BASE_URL=http://<stt-host>:8000/v1
STT_MODEL=CohereLabs/cohere-transcribe-arabic-07-2026
STT_LANGUAGE=ar
TTS_PROVIDER=openai
TTS_BASE_URL=http://<tts-host>:8081/v1
TTS_MODEL=bosonai/higgs-audio-v3-tts-4b
TTS_RESPONSE_FORMAT=pcm
TTS_VOICE=none
```

- **TTS streaming.** The OpenAI TTS plugin asks for `stream_format=sse`, which vLLM-Omni accepts only with `response_format` `pcm` or `wav`, so the plugin default `mp3` is rejected with HTTP 400. `TTS_RESPONSE_FORMAT=pcm` fixes that: first audio arrives after about 0.45 s, against about 4.4 s when the server renders the whole clip first.
- **Voice.** Higgs has no built-in speakers and rejects any voice name that was not uploaded (`POST /v1/audio/voices`), but speaks with its default voice when none is sent. `TTS_VOICE=none` sends none. Cloning from `ref_audio` failed on the tested server (its audio tokenizer weights were missing from the Hugging Face cache).
- **STT language.** `STT_LANGUAGE=ar` gives the most exact Arabic but forces Arabic output, so English speech comes out as Arabic nonsense. Leave it blank (automatic detection) when callers use both languages: English and Arabic were both transcribed exactly in the scripted calls, with an occasional stray Latin letter in Arabic text in direct tests.
- **Turn ending.** On an English question the local end-of-turn model waited the full `MAX_ENDPOINTING_DELAY` (3 s) before the agent replied, against 0.8 s for the Arabic one. Lower `MAX_ENDPOINTING_DELAY` if English replies feel slow.
- **Context.** The Qwen server's context is 8096 tokens, so keep `GRAPH_MAX_HISTORY_MESSAGES` low (12) and set `OPENAI_MAX_TOKENS`.
- **Known quirks.** The 4B model occasionally repeats its previous reply on the next turn (1 of 12 repeated two-turn runs with the agent's tools bound; 0 of 12 with `OPENAI_TEMPERATURE=0.3`, `OPENAI_PRESENCE_PENALTY=0.5` or `OPENAI_REPETITION_PENALTY=1.1`, which is too few runs to prove those settings help). Higgs sometimes repeats the last word of a sentence, streamed or not.

### Adapting to another model

Most differences between models are absorbed by settings, so a new model is usually an `.env` change:

| Symptom | Setting |
| --- | --- |
| HTTP 400 on every tool call (vLLM) | Not a project setting: start vLLM with `--enable-auto-tool-choice --tool-call-parser <parser>` |
| Slow first word, model thinks aloud | `OPENAI_ENABLE_THINKING=false` (models whose chat template reads it) |
| Repeats itself, flat or odd wording | `OPENAI_TEMPERATURE`, `OPENAI_TOP_P`, `OPENAI_PRESENCE_PENALTY`, `OPENAI_REPETITION_PENALTY`, `OPENAI_TOP_K`, `OPENAI_MIN_P` |
| Context window overflows (small models) | `GRAPH_MAX_HISTORY_MESSAGES`, `GRAPH_MAX_HISTORY_CHARS`, `OPENAI_MAX_TOKENS` |
| Replies in the wrong language or style | `AGENT_INSTRUCTIONS` (for example `Always answer in Arabic.`) |
| Embedding model expects prefixes or instructions | `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_DOCUMENT_PREFIX`, then a new `QDRANT_COLLECTION` |
| Speech plays too fast or too slow | `TTS_SAMPLE_RATE` must equal the model's rate when `TTS_RESPONSE_FORMAT=pcm` |
| TTS rejects the voice name | `TTS_VOICE=none` |
| TTS streaming answers HTTP 400 | `TTS_RESPONSE_FORMAT=pcm` (or `wav`) |
| Names or jargon misheard | `STT_PROMPT`, `STT_TEMPERATURE` |
| A server without auth refuses to start the app | Leave `OPENAI_API_KEY` and `EMBEDDING_API_KEY` blank: a custom base URL needs none |

Measured against the servers above:

- **Seed.** The same `OPENAI_SEED` gave the same sentence twice, and vLLM accepted `top_p`, both penalties, `top_k`, `min_p` and `repetition_penalty` together.
- **Embedding prefix.** On six questions over six passages, Qwen3-Embedding ranked all six correctly with and without its instruction prefix (average margin 0.20 without, 0.18 with), so the prefix did not help there. Test it on your own documents before keeping it.
- **`EMBEDDING_DIMENSIONS`.** The Qwen3 server answered HTTP 400, because it was not started with Matryoshka support. The setting only works for servers and models that allow shortened vectors.
- **`TTS_SPEED`.** Higgs answers HTTP 400 for any value other than 1.0 while streaming ("Speed adjustment is not supported when streaming"), and the plugin always streams. Keep 1.0 there.
- **`TTS_SAMPLE_RATE`.** Telling the plugin 12000 Hz for Higgs's 24000 Hz audio stretched a 4.3 s sentence to 8.4 s, which is the effect of a wrong rate.
- **`TTS_INSTRUCTIONS`, `STT_PROMPT`, `STT_TEMPERATURE`.** All three were accepted. Whether Higgs changes its voice for `TTS_INSTRUCTIONS` was not checked.

- **Embeddings.** `Qwen/Qwen3-Embedding-0.6B` on vLLM works with the stock client (`EMBEDDING_BASE_URL=http://<host>:8001/v1`, no key needed) and returns 1024 dimensions. Use a new `QDRANT_COLLECTION`, because the old one holds Cohere vectors of another size. Cosine scores were 0.45 to 0.62 for matching passages and 0.03 to 0.16 for unrelated text, in English and Arabic, so `RAG_SCORE_THRESHOLD=0.3` filters noise. With a handbook indexed, the agent called `knowledge_search` and answered correctly in both languages, and said so when a topic was not in the documents.

`scripts/check_models.py` calls the servers through the project's own service classes (LLM reply, first token and tool call; embedding ranking; TTS, then an STT round trip) and prints one line per check.

## Tracing

`TRACING_PROVIDER` is `none` or `langsmith`.

1. Set `TRACING_PROVIDER=langsmith`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT`.
2. `Tracing.get_callbacks()` returns a `LangChainTracer`; `build_run_config` (`src/graph/trace.py`) puts it in the `RunnableConfig` with the `thread_id`, tags (`omnivox`, `text` or `voice`) and metadata (`request_id`, `service`, `session_id`) of every graph run.
3. The voice worker also records each reply's latency summary as a `voice.turn` run.
4. Tracing errors are logged and swallowed; `Tracing.flush()` runs on shutdown.

With `none`, `get_callbacks()` returns an empty list and nothing leaves the process.
