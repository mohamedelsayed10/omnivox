# OmniVox

A real-time voice agent. You talk to it in the browser; LiveKit carries the audio; VAD, streaming speech-to-text and an end-of-turn model decide when you are done; a LangGraph agent (Gemini through an OpenAI-compatible API) answers, searching the web with ddgs or your own documents in Qdrant; streaming text-to-speech talks back. A web GUI shows the call and an Inspector that exposes every internal step.

```mermaid
flowchart LR
    gui([Browser GUI]):::io -- REST / SSE --> api[FastAPI /api/v1]:::api
    api --> svc[[Chat, knowledge and token services]]:::svc
    svc --> lg[[LangGraph agent]]:::svc
    gui <-- WebRTC audio + omnivox.trace --> lk[LiveKit server]:::api
    lk <--> worker[[Voice worker]]:::svc
    worker --> speech{{VAD, STT, end of turn, TTS}}:::llm
    worker --> lg
    lg --> llm{{Gemini via OpenAI API}}:::llm
    lg --> web>web_search: ddgs]:::tool
    lg --> kb>knowledge_search]:::tool
    kb --> emb{{Cohere embeddings}}:::llm
    kb --> qd[(Qdrant)]:::mem
    svc -.-> err([Standard JSON error]):::err

    classDef io fill:#FAFAFA,stroke:#616161,color:#212121
    classDef api fill:#E3F2FD,stroke:#1565C0,color:#0D47A1
    classDef svc fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20
    classDef llm fill:#F3E5F5,stroke:#6A1B9A,color:#4A148C
    classDef tool fill:#FFF3E0,stroke:#EF6C00,color:#E65100
    classDef mem fill:#ECEFF1,stroke:#455A64,color:#263238
    classDef err fill:#FFEBEE,stroke:#C62828,color:#B71C1C
```

Legend: stadium = client or response, rectangle = route or server, subroutine = service, hexagon = model, flag = tool or external API, cylinder = storage, dashed = error path.

The agent graph (details in [docs/graph.md](docs/graph.md)):

```mermaid
flowchart LR
    turn([User turn]):::io --> agent{{agent: Gemini + tools}}:::llm
    agent --> route{tool calls?}:::dec
    route -- yes --> tools[[tools]]:::svc --> agent
    route -- no --> done([Answer]):::io
    agent -.-> err([Error event]):::err

    classDef io fill:#FAFAFA,stroke:#616161,color:#212121
    classDef svc fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20
    classDef llm fill:#F3E5F5,stroke:#6A1B9A,color:#4A148C
    classDef dec fill:#FFFDE7,stroke:#F9A825,color:#F57F17
    classDef err fill:#FFEBEE,stroke:#C62828,color:#B71C1C
```

## Quick start

```bash
make install && make env       # then fill in the keys in .env
make up                        # everything in Docker: LiveKit, Qdrant, API, agent, GUI on http://localhost:8080
```

Or develop locally with only LiveKit and Qdrant in Docker:

```bash
make docker-infra-up           # LiveKit and Qdrant
make run                       # API on http://localhost:8100, in one terminal
make agent                     # voice worker, in a second terminal
make frontend-install && make frontend-dev   # GUI on http://localhost:5173
```

No `make` (Windows)? See [docs/installation.md](docs/installation.md).

## Project structure

```text
config/        settings (Pydantic) and logging
src/app.py     FastAPI app factory and entry point
src/api/       routes, schemas, middleware, error handlers, dependency wiring
src/services/  chat, knowledge base and LiveKit token use cases
src/graph/     LangGraph state, nodes, tools, memory, tracing, streaming
src/ai_models/ the only code that builds model clients (LLM, embeddings, STT, TTS, VAD, turn)
src/rag/       loading, chunking and retrieval over Qdrant
src/clients/   Qdrant and web search wrappers
src/voice/     LiveKit worker, session and Inspector
src/prompts/   all prompt text
src/utils/     pure helpers and domain errors
frontend/      React + TypeScript GUI
deployment/    Dockerfiles, compose, nginx and systemd templates
tests/         offline test suite
docs/ examples/ scripts/
```

## Documentation

[**Study guide, one page per block**](docs/blocks/README.md) · [Installation](docs/installation.md) · [Running](docs/running.md) · [Configuration](docs/config.md) · [API](docs/api.md) · [Voice and Inspector](docs/voice.md) · [Graph](docs/graph.md) · [Models and tracing](docs/llm.md) · [Prompts](docs/prompts.md) · [Helpers](docs/utils.md) · [Features and assumptions](docs/features.md) · [Deployment](docs/deployment.md) · [GUI](docs/frontend.md) · [Examples](examples/) · [Postman collection](docs/api_integration/collections/collection.json)
