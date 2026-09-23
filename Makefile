# NetworkOps Manager - developer & operator shortcuts.  `make help` lists the targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON        ?= python3.12
BACKEND_VENV  ?= backend/.venv
AGENT_VENV    ?= tacacs-agent/.venv
SDK_VENV      ?= sdk/python/.venv
BPY           := $(abspath $(BACKEND_VENV))/bin
COMPOSE       ?= docker compose
OPENAPI_GENERATOR_IMAGE ?= openapitools/openapi-generator-cli:v7.10.0
NOM_TEST_DATABASE_URL   ?= postgresql+psycopg://nom:nom@localhost:5432/nom_test
export NOM_TEST_DATABASE_URL

.PHONY: help
help: ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- local development -------------------------------------------------------------------------

$(BACKEND_VENV)/bin/python:
	$(PYTHON) -m venv $(BACKEND_VENV)
	$(BACKEND_VENV)/bin/pip install -U pip
	$(BACKEND_VENV)/bin/pip install -e "backend[dev,collectors]"

$(AGENT_VENV)/bin/python:
	$(PYTHON) -m venv $(AGENT_VENV)
	$(AGENT_VENV)/bin/pip install -e "tacacs-agent[dev]"

$(SDK_VENV)/bin/python:
	$(PYTHON) -m venv $(SDK_VENV)
	$(SDK_VENV)/bin/pip install -e "sdk/python[dev]"

.PHONY: venv
venv: $(BACKEND_VENV)/bin/python $(AGENT_VENV)/bin/python $(SDK_VENV)/bin/python ## Create all Python virtualenvs

.PHONY: dev-deps
dev-deps: ## Start PostgreSQL + Redis for local development (docker compose)
	$(COMPOSE) up -d postgres redis
	@echo "Postgres on the compose network; publish it locally with a compose override or use a local server."

.PHONY: dev
dev: $(BACKEND_VENV)/bin/python migrate ## Run the API with auto-reload (http://localhost:8000/api/docs)
	cd backend && $(BPY)/uvicorn app.main:app --reload --port 8000

.PHONY: dev-worker
dev-worker: $(BACKEND_VENV)/bin/python ## Run a Celery worker (all queues) + beat in one process
	cd backend && $(BPY)/celery -A app.workers.celery_app worker -B -Q collect,alerts,celery --loglevel info

.PHONY: dev-frontend
dev-frontend: ## Run the Next.js dev server (http://localhost:3000)
	cd frontend && npm install && npm run dev

.PHONY: migrate
migrate: $(BACKEND_VENV)/bin/python ## alembic upgrade head (NOM_DATABASE_URL)
	cd backend && $(BPY)/alembic upgrade head

.PHONY: init
init: $(BACKEND_VENV)/bin/python ## Create the first tenant + superuser admin (prompts for the password)
	cd backend && $(BPY)/python -m app.cli init --name Default --slug default --username admin --superuser

# --- quality -----------------------------------------------------------------------------------

.PHONY: test
test: test-backend test-agent test-sdk ## Run backend, agent and SDK tests
	@command -v npm >/dev/null && [ -d frontend/node_modules ] && (cd frontend && npm test) || echo "skipping frontend tests (npm ci first)"

.PHONY: test-backend
test-backend: $(BACKEND_VENV)/bin/python ## Backend tests (needs PostgreSQL: NOM_TEST_DATABASE_URL)
	cd backend && $(BPY)/pytest

.PHONY: test-agent
test-agent: $(AGENT_VENV)/bin/python ## TACACS agent tests
	cd tacacs-agent && .venv/bin/pytest

.PHONY: test-sdk
test-sdk: $(SDK_VENV)/bin/python ## Python + Go SDK tests
	cd sdk/python && .venv/bin/pytest
	cd sdk/go/networkops && go test -race ./...

.PHONY: lint
lint: venv ## ruff, mypy (SDK), gofmt/go vet, eslint + tsc
	cd backend && $(BPY)/ruff check .
	cd tacacs-agent && .venv/bin/ruff check src tests
	cd sdk/python && .venv/bin/ruff check src tests && .venv/bin/mypy
	cd sdk/go/networkops && test -z "$$(gofmt -l .)" && go vet ./...
	@[ -d frontend/node_modules ] && (cd frontend && npm run lint && npm run typecheck) || echo "skipping frontend lint (npm ci first)"

# --- end-to-end -------------------------------------------------------------------------------
# Full local stack (PostgreSQL + Redis must run; root or passwordless sudo for sshd/useradd).
# See e2e/README.md.

.PHONY: e2e-deps
e2e-deps: $(BACKEND_VENV)/bin/python $(AGENT_VENV)/bin/python ## Build tac_plus-ng and install the E2E Python/Node dependencies
	e2e/scripts/build-tac-plus-ng.sh
	test -x e2e/.venv/bin/python || $(PYTHON) -m venv e2e/.venv
	e2e/.venv/bin/pip install -q -r e2e/requirements.txt
	cd e2e && npm ci
	test -d frontend/node_modules || (cd frontend && npm ci)

.PHONY: e2e
e2e: ## Full-stack E2E: stack-up -> API suite + Playwright -> stack-down (non-zero on failure)
	e2e/scripts/run.sh

.PHONY: e2e-up
e2e-up: ## Start the E2E stack and leave it running (web :3000, API :8000, TACACS+ :4949, ssh :2222)
	e2e/scripts/stack-up.sh

.PHONY: e2e-down
e2e-down: ## Stop the E2E stack and drop its database
	e2e/scripts/stack-down.sh

.PHONY: check-manifests
check-manifests: ## docker compose config + kustomize build of every overlay
	$(COMPOSE) config -q
	for o in staging production; do kubectl kustomize deploy/k8s/overlays/$$o >/dev/null && echo "$$o ok"; done

# --- API contract & SDKs -----------------------------------------------------------------------

.PHONY: openapi
openapi: $(BACKEND_VENV)/bin/python ## Export docs/api/openapi.json from the backend code
	cd backend && NOM_ENVIRONMENT=test $(BPY)/python -m app.cli export-openapi --output ../docs/api/openapi.json

.PHONY: sdk
sdk: ## Generate python + go clients into sdk/generated/ with openapi-generator (Docker)
	@test -f docs/api/openapi.json || (echo "docs/api/openapi.json missing - run 'make openapi'" && exit 1)
	rm -rf sdk/generated && mkdir -p sdk/generated/python sdk/generated/go
	cp sdk/openapi-generator/.openapi-generator-ignore sdk/generated/python/
	cp sdk/openapi-generator/.openapi-generator-ignore sdk/generated/go/
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR):/local" $(OPENAPI_GENERATOR_IMAGE) generate \
		-i /local/docs/api/openapi.json -g python \
		-c /local/sdk/openapi-generator/python.yaml -o /local/sdk/generated/python
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR):/local" $(OPENAPI_GENERATOR_IMAGE) generate \
		-i /local/docs/api/openapi.json -g go \
		-c /local/sdk/openapi-generator/go.yaml -o /local/sdk/generated/go
	@echo "generated clients in sdk/generated/{python,go}"

# --- containers --------------------------------------------------------------------------------

.PHONY: images
images: ## Build backend, frontend and tacacs images
	docker build -t networkops/backend:dev backend
	docker build -t networkops/frontend:dev frontend
	docker build -t networkops/tacacs:dev tacacs-agent

.PHONY: compose-up
compose-up: ## Build and start the full stack (docker compose)
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example - set the secrets, then re-run" && exit 1)
	$(COMPOSE) up -d --build

.PHONY: compose-init
compose-init: ## First-run bootstrap inside compose (NOM_INIT_* from .env)
	$(COMPOSE) run --rm init

.PHONY: compose-down
compose-down: ## Stop the stack (volumes are kept)
	$(COMPOSE) down

.PHONY: compose-logs
compose-logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100
