.PHONY: help install test db-up db-down db-reset db-test check api web eval eval-live eval-baseline

PG_CONTAINER := beehub-pg
PG_IMAGE     := pgvector/pgvector:pg17
PG_PORT      := 55433
PG_DB        := beehub
PSQL         := docker exec -i $(PG_CONTAINER) psql -U postgres -d $(PG_DB)
VENV         := apps/api/.venv/bin

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install backend deps
	cd apps/api && python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"

test: ## Tier 0 tests — no network, no API key, no cost
	cd apps/api && .venv/bin/python -m pytest -q

db-up: ## Start local Postgres with pgvector
	@docker start $(PG_CONTAINER) 2>/dev/null || \
	  docker run -d --rm --name $(PG_CONTAINER) \
	    -e POSTGRES_PASSWORD=beehub -e POSTGRES_DB=$(PG_DB) \
	    -p $(PG_PORT):5432 $(PG_IMAGE) >/dev/null
	@for i in $$(seq 1 60); do \
	  docker exec $(PG_CONTAINER) pg_isready -U postgres -q 2>/dev/null && break; sleep 1; done
	@echo "postgres ready on localhost:$(PG_PORT)"

db-down: ## Stop local Postgres
	@docker rm -f $(PG_CONTAINER) >/dev/null 2>&1 || true

db-reset: db-up ## Drop, recreate, and re-apply every migration
	@docker exec -i $(PG_CONTAINER) psql -U postgres --no-psqlrc -q \
	  -c "drop database if exists $(PG_DB) with (force);" >/dev/null
	@docker exec -i $(PG_CONTAINER) psql -U postgres --no-psqlrc -q \
	  -c "create database $(PG_DB);" >/dev/null
	@# auth.users / auth.uid() are provided by Supabase in the real project;
	@# this is a local stand-in so migrations can be applied and tested offline.
	@docker cp supabase/local/auth_stub.sql $(PG_CONTAINER):/tmp/ >/dev/null
	@$(PSQL) -q -f /tmp/auth_stub.sql 2>&1 | grep -v "already exists" || true
	@# 0004_storage.sql needs Supabase's storage schema, which plain Postgres
	@# does not have. Skipped locally; applied to the real project only.
	@for f in supabase/migrations/*.sql; do \
	  case "$$f" in *_storage.sql) echo "  skipping $$(basename $$f) (needs Supabase storage schema)"; continue;; esac; \
	  echo "  applying $$(basename $$f)"; \
	  docker cp $$f $(PG_CONTAINER):/tmp/ >/dev/null; \
	  $(PSQL) -v ON_ERROR_STOP=1 -q -f /tmp/$$(basename $$f) || exit 1; \
	done
	@echo "schema up to date"

db-test: db-reset ## Run the position-gate / grounding SQL tests
	@docker cp supabase/tests/gate_test.sql $(PG_CONTAINER):/tmp/ >/dev/null
	@$(PSQL) -v ON_ERROR_STOP=1 -q -f /tmp/gate_test.sql

eval: ## Replay evals from cassettes (free) — fails if a prompt changed
	@$(VENV)/python evals/runner.py --suite all

eval-live: ## Run evals against the real API and re-record (~$0.60)
	@echo "This calls the Anthropic API and costs roughly \$$0.60."
	@$(VENV)/python evals/runner.py --suite all --live --verbose

eval-baseline: ## Re-record cassettes AND reset the baseline (deliberate reset)
	@$(VENV)/python evals/runner.py --suite all --live --update-baseline --verbose

check: test db-test eval ## Everything that runs for free
	@echo "all checks passed"

api: ## Run the API locally
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Run the frontend locally
	cd apps/web && npm run dev
