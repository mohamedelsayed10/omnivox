# Running

A full voice setup is five processes: LiveKit, Qdrant, the API, the voice worker and (optionally) the GUI. Pick one of three ways to run them; all read the same `.env` ([installation.md](installation.md) covers the keys).

| Way | Use it for | Commands |
| --- | --- | --- |
| [Everything in Docker](#everything-in-docker) | the simplest start, any OS | `make up` |
| [Local development](#local-development) | editing code with reload | `make docker-infra-up`, `make run`, `make agent` |
| [systemd on a Linux server](#systemd-on-a-linux-server) | boot-time start, restarts, logs in the journal | `make systemd-docker-install` or `make deploy-all` |

No `make` (Windows)? Each target is a thin wrapper; [installation.md](installation.md) lists the direct commands.

## Everything in Docker

```bash
make up        # builds the images and starts LiveKit, Qdrant, API, voice worker and GUI
make docker-ps   # container status (the API, worker and Qdrant report healthy)
make docker-logs
make down      # stops and removes the containers; the Qdrant data is kept
```

Open http://localhost:8080, press the call button and allow the microphone. The API is on http://localhost:8100 (`GET /health`), and `bash examples/curl.sh` exercises every endpoint.

- **No GUI:** `make docker-up` starts everything except the GUI container.
- **After changing `.env`:** `make restart` rebuilds and recreates every container. Compose reads `.env` only when a container is created.
- **Qdrant:** a bundled container with the named volume `qdrant_data`, so uploaded documents survive `make down` and `make restart` (only `docker compose down -v` deletes them). It listens on `127.0.0.1:6333`; if that port is taken, set `QDRANT_HOST_PORT=6335` in `.env`. To use a Qdrant you already run, set `QDRANT_DOCKER_URL=http://host.docker.internal:6333/`.
- **Other machines:** browsers on other machines need the LiveKit media address: set `LIVEKIT_NODE_IP` to the host's LAN or public IP and `LIVEKIT_PUBLIC_URL` to the matching `ws://` or `wss://` URL, then `make restart`. The worker needs nothing: it shares LiveKit's network ([deployment.md](deployment.md)).
- **Ports:** API `PORT` (8100), GUI `FRONTEND_PORT` (8080), LiveKit 7880, 7881/tcp and 7882/udp, Qdrant `QDRANT_HOST_PORT` (6333).

## Local development

LiveKit and Qdrant run in Docker; the Python processes run from your checkout so code changes apply at once.

```bash
make docker-infra-up   # LiveKit on :7880 and Qdrant on :6333
make run               # API on http://localhost:8100  (GET /health), in one terminal
make agent             # voice worker, registers with LiveKit, in a second terminal
make frontend-dev      # GUI on http://localhost:5173 (proxies /api to the API), in a third
```

Open http://localhost:5173, press the call button and allow the microphone.

- Text chat and the knowledge base need only `make run` (and Qdrant); see [api.md](api.md) and [examples/](../examples/).
- `make dev` reloads the API on code changes (`RELOAD=true`); `make agent-dev` does the same for the worker. If the worker's dev mode misbehaves on your platform use `make agent`.
- The API takes a few seconds to start because it imports the LiveKit plugins; wait for "Application startup complete" before calling it.
- Port 8000 is often taken by other tools, so the default is `PORT=8100`. If `QDRANT_HOST_PORT` is not 6333, set `QDRANT_URL` in `.env` to match.
- `make docker-infra-down` stops LiveKit and Qdrant.

## systemd on a Linux server

Two setups, both started and stopped with `systemctl`. Prerequisites: Docker with Compose, the repository in its final folder (for example `/opt/omnivox`), and `.env` filled in. For browsers on other machines also set `LIVEKIT_NODE_IP` and `LIVEKIT_PUBLIC_URL`, and replace the development `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`.

### A. Docker runs everything, systemd runs Docker

```bash
sudo usermod -aG docker "$USER"     # once, then log in again: the service user must use Docker
make systemd-docker-install         # renders omnivox-docker.service, enables it and starts it now
```

The unit runs `docker compose up -d --build` at boot and `docker compose down` on stop, after `docker.service`. The first start builds the images, so allow a few minutes.

```bash
sudo systemctl status omnivox-docker
sudo systemctl restart omnivox-docker   # after editing .env
sudo systemctl stop omnivox-docker
sudo journalctl -u omnivox-docker -f    # the unit's own output
make docker-logs                        # the containers' logs
make systemd-docker-uninstall           # stop, disable and remove the unit
```

### B. Docker for LiveKit and Qdrant, systemd for the Python processes

```bash
make docker-infra-up                          # LiveKit and Qdrant containers (they restart with Docker)
make deploy-app                               # uv sync, installs and (re)starts omnivox and omnivox-agent
make deploy-gui SERVER_NAME=ai.example.com    # the same plus the built GUI served by nginx
make deploy-all                               # infra containers, both services and nginx in one command
```

`.env` must point at the host: `LIVEKIT_URL=ws://localhost:7880` and `QDRANT_URL=http://localhost:6333/` (use `QDRANT_HOST_PORT` in both places if 6333 is taken).

```bash
sudo systemctl status omnivox omnivox-agent
sudo systemctl restart omnivox omnivox-agent   # after editing .env
sudo journalctl -u omnivox -u omnivox-agent -f
make systemd-status
make systemd-logs
make systemd-uninstall                         # remove the two services
make docker-infra-down                         # stop LiveKit and Qdrant
```

Both units restart on failure after five seconds. The units, nginx site and every Make target are described in [deployment.md](deployment.md).

## Tests

```bash
make test    # offline: fake models, in-memory Qdrant, no keys, no network
make check   # ruff lint + format check + tests
make smoke   # real providers, needs real keys; not part of the test run
```

Logs go to the console and to `files/logs/omnivox.log` (rotating). Set `LOG_FORMAT=json` for structured logs.
