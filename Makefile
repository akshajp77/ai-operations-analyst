# Developer entrypoint.
#
# One command surface for a two-language repository. Nobody should have to
# remember whether the linter is `ruff` or `eslint`, or which directory to run
# it from — `make lint` does the right thing for both. CI calls exactly these
# targets, so "passes locally" and "passes in CI" cannot drift apart.
#
# Run `make` with no arguments for the list.

.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND  := backend
FRONTEND := frontend
COMPOSE  := docker compose
VENV     := $(BACKEND)/.venv

.PHONY: help
help: ## Show this help
	@echo "AI Operations Analyst — available targets:"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
.PHONY: install
install: install-backend install-frontend ## Install all dependencies

.PHONY: install-backend
install-backend: ## Create the venv and install backend dependencies
	@command -v python3.12 >/dev/null 2>&1 || { \
		echo "ERROR: python3.12 not found."; \
		echo "  macOS: brew install python@3.12"; \
		echo "  Or run 'make up' to use Docker instead — it ships 3.12."; \
		exit 1; }
	python3.12 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e "./$(BACKEND)[dev]"

.PHONY: install-frontend
install-frontend: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

.PHONY: env
env: ## Create .env files from the tracked examples
	@[ -f .env ] || cp .env.example .env
	@[ -f $(BACKEND)/.env ] || cp $(BACKEND)/.env.example $(BACKEND)/.env
	@[ -f $(FRONTEND)/.env.local ] || cp $(FRONTEND)/.env.example $(FRONTEND)/.env.local
	@echo "Environment files ready. Add your OPENAI_API_KEY to $(BACKEND)/.env"

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
.PHONY: up
up: ## Start the full stack in Docker (db + api + web)
	$(COMPOSE) up --build -d
	@echo "  API  http://localhost:8000/docs"
	@echo "  Web  http://localhost:3000"

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: clean-volumes
clean-volumes: ## Stop the stack AND delete the database volume (destructive)
	$(COMPOSE) down --volumes

.PHONY: logs
logs: ## Tail logs from all services
	$(COMPOSE) logs -f

.PHONY: dev-backend
dev-backend: ## Run the API natively with hot reload
	cd $(BACKEND) && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

.PHONY: dev-frontend
dev-frontend: ## Run the web app natively with hot reload
	cd $(FRONTEND) && npm run dev

# ---------------------------------------------------------------------------
# Quality gates — these are exactly what CI runs
# ---------------------------------------------------------------------------
.PHONY: check
check: lint typecheck test ## Everything CI runs. Use before opening a PR.

.PHONY: lint
lint: lint-backend lint-frontend ## Lint both projects

.PHONY: lint-backend
lint-backend:
	cd $(BACKEND) && ../$(VENV)/bin/ruff check .
	cd $(BACKEND) && ../$(VENV)/bin/ruff format --check .

.PHONY: lint-frontend
lint-frontend:
	cd $(FRONTEND) && npm run lint
	cd $(FRONTEND) && npm run format:check

.PHONY: format
format: ## Auto-fix formatting and safe lint violations
	cd $(BACKEND) && ../$(VENV)/bin/ruff check --fix .
	cd $(BACKEND) && ../$(VENV)/bin/ruff format .
	cd $(FRONTEND) && npm run format

.PHONY: typecheck
typecheck: ## Static type checking for both projects
	cd $(BACKEND) && ../$(VENV)/bin/mypy app
	cd $(FRONTEND) && npm run typecheck

.PHONY: test
test: test-backend test-frontend ## Run all tests

.PHONY: test-backend
test-backend:
	cd $(BACKEND) && ../$(VENV)/bin/pytest

.PHONY: test-unit
test-unit: ## Backend unit tests only — the fast inner loop
	cd $(BACKEND) && ../$(VENV)/bin/pytest -m unit

.PHONY: test-frontend
test-frontend:
	cd $(FRONTEND) && npm run test:run

.PHONY: coverage
coverage: ## Backend tests with a coverage report
	cd $(BACKEND) && ../$(VENV)/bin/pytest --cov --cov-report=term-missing --cov-report=html
	@echo "HTML report: $(BACKEND)/htmlcov/index.html"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply all pending migrations
	cd $(BACKEND) && ../$(VENV)/bin/alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back the most recent migration
	cd $(BACKEND) && ../$(VENV)/bin/alembic downgrade -1

.PHONY: migration
migration: ## Generate a migration. Usage: make migration m="add datasets table"
	@[ -n "$(m)" ] || { echo 'Usage: make migration m="description"'; exit 1; }
	cd $(BACKEND) && ../$(VENV)/bin/alembic revision --autogenerate -m "$(m)"
	@echo "Review the generated file before committing — autogenerate is a draft, not an answer."

.PHONY: db-shell
db-shell: ## Open psql against the Compose database
	$(COMPOSE) exec db psql -U postgres -d ai_ops_analyst

# ---------------------------------------------------------------------------
# Shared types — the frontend/backend contract
# ---------------------------------------------------------------------------
.PHONY: types
types: ## Regenerate TypeScript types from the backend's OpenAPI schema
	cd $(BACKEND) && ../$(VENV)/bin/python -c \
		"import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" \
		> ../packages/shared-types/openapi.json
	cd $(FRONTEND) && npm run generate:types
	@echo "Types regenerated. Commit the diff alongside the backend change that caused it."
