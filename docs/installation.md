# Installation

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Python | 3.12 (3.10 is the minimum) | API and voice worker |
| [uv](https://docs.astral.sh/uv/) | 0.12 or newer | Dependencies and running commands |
| Docker | 24 or newer (Compose 2.24 or newer) | LiveKit, Qdrant and the container deployment |
| Node.js | 22 | Web GUI (`frontend/`) |
| Qdrant | 1.x at `QDRANT_URL` | Knowledge base. The compose file bundles one (`make up`, `make docker-infra-up`); otherwise run your own, for example `docker run -p 6333:6333 qdrant/qdrant` |
| GNU make | any | Optional shortcuts (`make help`) |

`uv` itself is tooling, not a project dependency. Install it from the uv documentation.

## Steps

```bash
make install     # uv sync: creates .venv from pyproject.toml
make env         # copies .env.example to .env (an existing .env is kept)
```

Then edit `.env`:

| Variable | Where to get it |
| --- | --- |
| `OPENAI_API_KEY` | A Gemini API key (Google AI Studio) for the default endpoint |
| `ELEVENLABS_API_KEY` | ElevenLabs API key, shown once at creation, starts with `sk_` |
| `EMBEDDING_API_KEY` | Cohere API key (knowledge base) |
| `LANGSMITH_API_KEY` | Optional, with `TRACING_PROVIDER=langsmith` |

ElevenLabs notes: a restricted API key only needs the text-to-speech and speech-to-text permissions (the app never lists voices or models). Free plans cannot use *library* voices through the API (HTTP 402 `paid_plan_required`), which is why the default voice is Sarah; Roger, George, Charlie, Laura, Alice, Brian and Lily also work, Rachel and Aria need a paid plan.

LiveKit needs no account: `docker compose` starts a local server whose development key and secret are already in `.env.example`.

Install the GUI dependencies with `make frontend-install`.

## Without make (Windows)

GNU make is usually missing on Windows. Every target is a thin wrapper, so run the commands directly:

| make | command |
| --- | --- |
| `make install` | `uv sync` |
| `make env` | `copy .env.example .env` |
| `make run` | `uv run python -m src.app` |
| `make agent` | `uv run python -m src.voice.worker start` |
| `make test` | `uv run pytest` |
| `make check` | `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` |
| `make frontend-install` / `frontend-dev` | `cd frontend && npm ci` / `npm run dev` |
| `make up` / `make docker-up-gui` | `docker compose --env-file .env -f deployment/docker-compose.yml --profile gui up -d --build` |
| `make down` | `docker compose --env-file .env -f deployment/docker-compose.yml --profile gui down` |
| `make restart` | `docker compose --env-file .env -f deployment/docker-compose.yml --profile gui up -d --build --force-recreate` |
| `make docker-infra-up` | `docker compose --env-file .env -f deployment/docker-compose.yml --profile infra up -d` |

If you prefer pip: `requirements.txt` pins the runtime dependencies (`pip install -r requirements.txt`); Docker and `make deploy-app` install from it. `make export-reqs` re-resolves and rewrites it from `pyproject.toml`.

## Verify

```bash
make test                           # offline suite, needs no keys
make run                            # then, in another terminal:
curl http://localhost:8100/health   # {"status":"ok", ...}
```
