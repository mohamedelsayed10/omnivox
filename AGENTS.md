# AGENTS.md

OmniVox: LiveKit voice agent + FastAPI + LangGraph. Read `README.md` and `docs/` before changing behavior.

## Layers (imports point downward only)

| Layer | May import | Never |
| --- | --- | --- |
| `src/api/routes`, `schemas` | services (via `Depends`), schemas, utils | call `ai_models` or `graph` directly, hold logic |
| `src/services` | graph, ai_models, rag, clients, prompts, config, utils | import FastAPI or `src/api` |
| `src/graph` | ai_models, rag, clients, prompts, config, utils | import `services` or `api` |
| `src/rag` | ai_models, clients, config, utils | import graph, services, api |
| `src/ai_models`, `src/clients` | config, utils | import prompts, graph, services |
| `src/prompts`, `src/utils`, `config` | stdlib and third parties only | import other `src` layers |

Composition roots: `src/app.py` + `src/api/deps.py` (API) and `src/voice/worker.py` (voice). Shared wiring is `src/composition.py`. Inject dependencies so tests can pass fakes.

## Commands

- `make check` = ruff lint + format check + offline tests. Run before finishing any change.
- `make up` runs everything in Docker (LiveKit, Qdrant, API, agent, GUI), `make down` stops it, `make restart` after editing `.env`; `make docker-infra-up` starts only LiveKit and Qdrant.
- `make test`, `make format`, `make schemas` (regenerate `docs/api_integration`), `make smoke` (real keys).
- `uv run python scripts/refresh_block_excerpts.py` refreshes the code excerpts in `docs/blocks/` after you change code they quote (a test fails on drift).
- No `make` on Windows: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.

## Never

- Print, log or commit secrets. Keys are `SecretStr`; `.env` is git-ignored.
- Build a model client outside `src/ai_models/`. Put prompt text outside `src/prompts/`.
- Use `print`, bare `except`, blocking calls in async code, or deprecated LangChain APIs (`LLMChain`, `initialize_agent`, `AgentExecutor`).
- Return stack traces, prompts or provider payloads in API responses.
- Add a setting without adding it to `.env.example` and `docs/config.md` (a test checks all three).
- Edit `docs/api_integration/**` or `requirements.txt` by hand; both are generated.
- Make tests depend on the network or real keys.

## Add a feature

1. Schema in `src/api/schemas/` (bounded lengths, `extra="forbid"`).
2. Prompt text in `src/prompts/` (bump `PROMPT_VERSION` if behavior changes).
3. Service in `src/services/`; framework-free, raise errors from `src/utils/exceptions.py`.
4. Route in `src/api/routes/`; thin, with `response_model` and error `responses`; register it in `src/app.py`.
5. Tests in the mirrored `tests/` folder, using the fakes in `tests/fakes.py`.
6. Docs (`docs/api.md`, `docs/features.md`), the generator in `scripts/export_schemas.py`, then `make schemas`.

New graph tool: module in `src/graph/tools/`, register in `build_tools`. New setting: `config/settings.py`, `.env.example`, regenerate the table in `docs/config.md`.

## Gotchas

- `ELEVENLABS_API_KEY` must start with `sk_`; free plans need a non-library voice (default Sarah). Port 8000 is often taken, the API uses 8100.
- LiveKit's `LLMAdapter` needs a graph compiled without a checkpointer; the voice session history lives in LiveKit.
- Gemini 3 tool calls need thought signatures replayed (`GeminiChatOpenAI`).
