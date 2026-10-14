# Shortcuts for common tasks. `make help` lists them.
.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down reset logs ps migrate test test-unit lint fmt check

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

up: ## Build and start everything, wait until healthy
	$(COMPOSE) up --build -d --wait
	@echo ""
	@echo "  Web app      http://localhost:8080"
	@echo "  API docs     http://localhost:8000/api/docs"
	@echo "  Mock Sarvam  http://localhost:9000/health"

down: ## Stop everything (keeps data)
	$(COMPOSE) down

reset: ## Stop everything and delete all data
	$(COMPOSE) down -v

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Run database migrations
	$(COMPOSE) run --rm migrate

test: ## Run all backend tests (integration tests need `make up` first)
	cd backend && uv run pytest
	cd mock_sarvam && uv run pytest

test-unit: ## Run only the fast tests (no database needed)
	cd backend && uv run pytest -m "not integration"

lint: ## Lint and type-check
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	cd mock_sarvam && uv run ruff check . && uv run ruff format --check .

fmt: ## Auto-format code
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd mock_sarvam && uv run ruff check --fix . && uv run ruff format .

check: lint test ## Everything CI runs (except the stack test)
