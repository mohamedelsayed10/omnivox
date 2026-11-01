# Deployment

Four ways to run it: everything in Docker Compose, Docker Compose started by systemd, Docker for LiveKit and Qdrant with the Python processes under systemd and nginx (Linux), or by hand ([running.md](running.md) has the step-by-step commands). Container and server setups need `.env` filled in first ([installation.md](installation.md)).

## Docker

`deployment/docker-compose.yml` has three profiles:

| Profile | Services |
| --- | --- |
| `app` | `livekit` (media server), `qdrant` (vector database), `api` (FastAPI), `agent` (voice worker) |
| `gui` | everything in `app` plus `frontend` (nginx serving the built GUI and proxying `/api`) |
| `infra` | `livekit` and `qdrant` only, for a host that runs the API and the worker under systemd |

```bash
make up                # everything: docker compose --env-file .env -f deployment/docker-compose.yml --profile gui up -d --build
make docker-ps
make restart           # rebuild and recreate after changing .env
make down              # the Qdrant volume is kept
make docker-infra-up   # only LiveKit and Qdrant
```

- One image (`deployment/Dockerfile`) runs both the API and the worker: multi-stage, `uv` copied from the pinned official image, `uv sync --frozen --no-dev`, non-root user, health check on `/health` using the standard library only. No secret is baked in: `.env` is passed with `env_file`.
- The GUI image (`deployment/Dockerfile.frontend`) builds `frontend/` and serves it with nginx, rendering `deployment/nginx/omnivox.conf.template` from the container environment.
- **Qdrant** is a container (`qdrant/qdrant:v1.20.0`) with the named volume `qdrant_data`, a health check, and a host port bound to `127.0.0.1:${QDRANT_HOST_PORT:-6333}`. The API and the worker wait for it to be healthy and reach it at `http://qdrant:6333/`. To use another Qdrant (for example one on your machine) set `QDRANT_DOCKER_URL=http://host.docker.internal:6333/`.
- Optional compose-only overrides (read by Compose, not by the app; commented out in `.env.example`, listed in [config.md](config.md)): `QDRANT_HOST_PORT` (default `6333`), `QDRANT_DOCKER_URL`, `LIVEKIT_NODE_IP` (default `127.0.0.1`) and `FRONTEND_PORT` (default `8080`).
- **LiveKit address.** `LIVEKIT_NODE_IP` is the address LiveKit tells clients to send media to. `127.0.0.1` is right for a browser on the same machine. For browsers on other machines set it to the host's LAN or public IP and set `LIVEKIT_PUBLIC_URL` to the matching `ws://` or `wss://` address.
- **The worker shares LiveKit's network** (`network_mode: "service:livekit"`), so `127.0.0.1` is the LiveKit server for it and media works without extra settings. `ports` and `extra_hosts` therefore sit on the `livekit` service, and `depends_on` with `restart: true` recreates the worker whenever LiveKit is recreated, and the GUI whenever the API is.
- Ports: LiveKit `7880` (signaling), `7881/tcp` and `7882/udp` (media); API `PORT`; GUI `FRONTEND_PORT`; Qdrant `QDRANT_HOST_PORT`.
- Compose reads `.env` only when it creates a container, so run `make restart` after editing it.

## systemd

Three templates in `deployment/systemd/` are rendered with `envsubst` limited to `SERVICE_NAME`, `INSTALL_DIR` and `RUN_USER`:

| Template | Unit | Runs |
| --- | --- | --- |
| `omnivox.service.template` | `omnivox.service` | the API (`python -m src.app`) |
| `omnivox-agent.service.template` | `omnivox-agent.service` | the voice worker (`python -m src.voice.worker start`) |
| `omnivox-docker.service.template` | `omnivox-docker.service` | the whole Docker stack: `docker compose up -d --build` on start, `down` on stop |

The API and worker units use `Type=simple`, `EnvironmentFile=<dir>/.env`, `Restart=on-failure`, `RestartSec=5` and are hardened with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` and `ReadWritePaths=<dir>/files`. Logs go to the journal. The Docker unit is `Type=oneshot` with `RemainAfterExit=yes`, `Requires=docker.service` and `TimeoutStartSec=900` because the first start builds the images; its user must be in the `docker` group. All three units pass `systemd-analyze verify`.

Two setups:

- **Docker runs everything, systemd starts it at boot:** `make systemd-docker-install`, then `sudo systemctl status|restart|stop omnivox-docker`.
- **Docker for the infrastructure, systemd for the Python processes:** `make docker-infra-up` (LiveKit and Qdrant), then `make deploy-app` or `make deploy-gui`; `make deploy-all` does all of it. `.env` needs `LIVEKIT_URL=ws://localhost:7880` and a `QDRANT_URL` that matches `QDRANT_HOST_PORT`.

Prerequisite for the second setup: the repository is in `INSTALL_DIR` and `uv` is installed (`make deploy-app` runs `uv sync --frozen --no-dev`, which creates `.venv` there). Commands for each setup are in [running.md](running.md).

## nginx

`deployment/nginx/omnivox.conf.template` is rendered with `envsubst` limited to `SERVICE_NAME`, `SERVER_NAME`, `API_UPSTREAM`, `FRONTEND_ROOT`, `REQUEST_TIMEOUT` and `CLIENT_MAX_BODY_SIZE`, so nginx's own `$host`-style variables survive. It provides:

- host mode: `http://SERVER_NAME/api/...` and `/health` proxied to `127.0.0.1:PORT`;
- path mode: `http://SERVER_NAME/<SERVICE_NAME>/...` proxied to the same upstream (set `ROOT_PATH=/<SERVICE_NAME>`);
- GUI mode: `/` serves `frontend/dist` with a single-page-app fallback.

It is safe for server-sent events: HTTP/1.1, `proxy_buffering off`, `proxy_read_timeout` equal to `REQUEST_TIMEOUT`, upgrade headers, `X-Forwarded-*`, `X-Request-ID`. A commented `limit_req` and a commented TLS block (certbot) are included. Browsers connect to LiveKit directly (`LIVEKIT_PUBLIC_URL`), not through nginx.

## Makefile targets

Variables `SERVICE_NAME` (from `APP_NAME`), `PORT`, `SERVER_NAME`, `INSTALL_DIR`, `RUN_USER` default from `.env` or the environment and can be overridden: `make deploy-gui SERVER_NAME=ai.example.com`. Privileged steps use an explicit `sudo`, nginx is reloaded only after `nginx -t` passes, and every target can be run again safely.

| Group | Targets |
| --- | --- |
| Setup | `install`, `env`, `export-reqs`, `schemas` |
| Development | `run`, `agent`, `agent-dev`, `dev`, `test`, `lint`, `format`, `check`, `smoke` |
| Docker | `up`, `down`, `restart`, `docker-build`, `docker-up`, `docker-up-gui`, `docker-down`, `docker-logs`, `docker-ps`, `docker-infra-up`, `docker-infra-down` |
| systemd | `systemd-install`, `systemd-start`, `systemd-stop`, `systemd-restart`, `systemd-status`, `systemd-logs`, `systemd-uninstall`, `systemd-docker-install`, `systemd-docker-uninstall` |
| nginx | `nginx-install`, `nginx-test`, `nginx-remove` |
| Combined | `deploy-app`, `deploy-gui`, `deploy-all`, `frontend-install`, `frontend-dev`, `frontend-build` |

`make help` prints them with descriptions.

## Production checklist

- `APP_ENV=production`, `API_KEYS` set, `CORS_ORIGINS` limited to the GUI origin.
- Replace the development LiveKit key and secret in `.env` (compose and the app read the same values).
- Serve the GUI and the LiveKit address over HTTPS and WSS (browsers only allow microphone capture on secure origins, `localhost` excepted).
- Keep `.env` out of version control and out of images (it is in `.gitignore` and `.dockerignore`).
