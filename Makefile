# OmniVox developer and deployment tasks. Run `make` to list them.
# Variables default from .env and can be overridden: make deploy-gui SERVER_NAME=ai.example.com

SHELL := /bin/bash
.DEFAULT_GOAL := help

env_value = $(shell sed -n 's/^$(1)=//p' .env 2>/dev/null | tail -n 1)

SERVICE_NAME ?= $(or $(call env_value,APP_NAME),omnivox)
PORT ?= $(or $(call env_value,PORT),8100)
REQUEST_TIMEOUT ?= $(or $(call env_value,REQUEST_TIMEOUT),60)
SERVER_NAME ?= _
INSTALL_DIR ?= $(CURDIR)
RUN_USER ?= $(shell id -un)
CLIENT_MAX_BODY_SIZE ?= 12m

COMPOSE := docker compose --env-file .env -f deployment/docker-compose.yml
UNITS := $(SERVICE_NAME).service $(SERVICE_NAME)-agent.service
SYSTEMD_DIR := /etc/systemd/system
NGINX_CONF := /etc/nginx/conf.d/$(SERVICE_NAME).conf
SYSTEMD_VARS := '$${SERVICE_NAME} $${INSTALL_DIR} $${RUN_USER}'
NGINX_VARS := '$${SERVICE_NAME} $${SERVER_NAME} $${API_UPSTREAM} $${FRONTEND_ROOT} $${REQUEST_TIMEOUT} $${CLIENT_MAX_BODY_SIZE}'

.PHONY: help install env export-reqs schemas run agent agent-dev dev test lint format check smoke \
	up down restart docker-build docker-up docker-up-gui docker-down docker-logs docker-ps \
	docker-infra-up docker-infra-down \
	systemd-install systemd-start systemd-stop systemd-restart systemd-status systemd-logs \
	systemd-uninstall systemd-docker-install systemd-docker-uninstall \
	nginx-install nginx-test nginx-remove \
	deploy-app deploy-gui deploy-all frontend-install frontend-dev frontend-build

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^##@/ {printf "\n%s\n", substr($$0, 5)} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Setup
install: ## Install Python dependencies with uv
	uv sync

env: ## Create .env from .env.example (keeps an existing .env)
	@if [ -f .env ]; then echo ".env already exists, left untouched"; else cp .env.example .env && echo "created .env, fill in the secrets"; fi

export-reqs: ## Write requirements.txt (pip fallback) from uv.lock
	uv export --no-dev --no-hashes -o requirements.txt

schemas: ## Regenerate docs/api_integration from the code
	uv run python scripts/export_schemas.py

##@ Development
run: ## Run the API on PORT
	uv run python -m src.app

agent: ## Run the LiveKit voice agent worker
	uv run python -m src.voice.worker start

agent-dev: ## Run the voice agent worker with auto reload
	uv run python -m src.voice.worker dev

dev: ## Run the API with auto reload
	RELOAD=true uv run python -m src.app

test: ## Run the offline test suite
	uv run pytest

lint: ## Check style and lint (ruff)
	uv run ruff check .
	uv run ruff format --check .

format: ## Format and auto-fix with ruff
	uv run ruff format .
	uv run ruff check . --fix

check: lint test ## Lint plus tests (run before committing)

smoke: ## Call the real providers once (needs real keys in .env)
	uv run python scripts/smoke_models.py

##@ Docker
up: docker-up-gui ## Run everything in Docker: LiveKit, Qdrant, API, agent and the GUI

down: docker-down ## Stop everything (the Qdrant data volume is kept)

restart: ## Rebuild and recreate every container (needed after changing .env)
	$(COMPOSE) --profile gui up -d --build --force-recreate

docker-build: ## Build the images
	$(COMPOSE) --profile gui build

docker-up: ## Start LiveKit, Qdrant, API and agent (no GUI)
	$(COMPOSE) --profile app up -d --build

docker-up-gui: ## Start LiveKit, Qdrant, API, agent and the web GUI
	$(COMPOSE) --profile gui up -d --build

docker-down: ## Stop and remove the containers
	$(COMPOSE) --profile gui --profile app --profile infra down

docker-logs: ## Follow container logs
	$(COMPOSE) --profile gui --profile app --profile infra logs -f --tail 100

docker-ps: ## List containers
	$(COMPOSE) --profile gui --profile app --profile infra ps

docker-infra-up: ## Start only LiveKit and Qdrant in Docker (for API and agent under systemd)
	$(COMPOSE) --profile infra up -d

docker-infra-down: ## Stop LiveKit and Qdrant
	$(COMPOSE) --profile infra down

##@ systemd (Linux, needs sudo)
systemd-install: ## Install and enable the API and agent services
	SERVICE_NAME='$(SERVICE_NAME)' INSTALL_DIR='$(INSTALL_DIR)' RUN_USER='$(RUN_USER)' envsubst $(SYSTEMD_VARS) < deployment/systemd/omnivox.service.template | sudo tee $(SYSTEMD_DIR)/$(SERVICE_NAME).service > /dev/null
	SERVICE_NAME='$(SERVICE_NAME)' INSTALL_DIR='$(INSTALL_DIR)' RUN_USER='$(RUN_USER)' envsubst $(SYSTEMD_VARS) < deployment/systemd/omnivox-agent.service.template | sudo tee $(SYSTEMD_DIR)/$(SERVICE_NAME)-agent.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable $(UNITS)

systemd-start: ## Start the services
	sudo systemctl start $(UNITS)

systemd-stop: ## Stop the services
	sudo systemctl stop $(UNITS)

systemd-restart: ## Restart the services
	sudo systemctl restart $(UNITS)

systemd-status: ## Show service status
	@sudo systemctl status $(UNITS) --no-pager || true

systemd-logs: ## Follow service logs
	sudo journalctl -u $(SERVICE_NAME) -u $(SERVICE_NAME)-agent -f

systemd-uninstall: ## Stop, disable and remove the services
	-sudo systemctl disable --now $(UNITS)
	sudo rm -f $(addprefix $(SYSTEMD_DIR)/,$(UNITS))
	sudo systemctl daemon-reload

systemd-docker-install: ## Install and start a service that runs the whole Docker stack at boot
	SERVICE_NAME='$(SERVICE_NAME)' INSTALL_DIR='$(INSTALL_DIR)' RUN_USER='$(RUN_USER)' envsubst $(SYSTEMD_VARS) < deployment/systemd/omnivox-docker.service.template | sudo tee $(SYSTEMD_DIR)/$(SERVICE_NAME)-docker.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE_NAME)-docker.service

systemd-docker-uninstall: ## Stop, disable and remove the Docker stack service
	-sudo systemctl disable --now $(SERVICE_NAME)-docker.service
	sudo rm -f $(SYSTEMD_DIR)/$(SERVICE_NAME)-docker.service
	sudo systemctl daemon-reload

##@ nginx (Linux, needs sudo)
nginx-install: ## Render the nginx site, test it and reload nginx
	SERVICE_NAME='$(SERVICE_NAME)' SERVER_NAME='$(SERVER_NAME)' API_UPSTREAM='127.0.0.1:$(PORT)' FRONTEND_ROOT='$(INSTALL_DIR)/frontend/dist' REQUEST_TIMEOUT='$(REQUEST_TIMEOUT)' CLIENT_MAX_BODY_SIZE='$(CLIENT_MAX_BODY_SIZE)' envsubst $(NGINX_VARS) < deployment/nginx/omnivox.conf.template | sudo tee $(NGINX_CONF) > /dev/null
	sudo nginx -t
	sudo systemctl reload nginx

nginx-test: ## Test the nginx configuration
	sudo nginx -t

nginx-remove: ## Remove the nginx site and reload nginx
	sudo rm -f $(NGINX_CONF)
	sudo nginx -t
	sudo systemctl reload nginx

##@ Combined
frontend-install: ## Install the GUI dependencies
	cd frontend && npm ci

frontend-dev: ## Run the GUI dev server on port 5173
	cd frontend && npm run dev

frontend-build: ## Build the GUI to frontend/dist
	cd frontend && npm run build

deploy-app: ## Install dependencies and (re)start API and agent under systemd
	uv sync --frozen --no-dev
	$(MAKE) systemd-install
	$(MAKE) systemd-restart

deploy-gui: frontend-install frontend-build ## deploy-app plus the GUI served by nginx
	$(MAKE) deploy-app
	$(MAKE) nginx-install

deploy-all: docker-infra-up deploy-gui ## LiveKit and Qdrant in Docker, API and agent under systemd, GUI under nginx
