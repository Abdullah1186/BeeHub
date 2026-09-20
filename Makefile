.PHONY: help install install-web test db-up db-down db-reset db-test check api web worker worker-once dev eval eval-live eval-baseline

PG_CONTAINER := beehub-pg
PG_IMAGE     := pgvector/pgvector:pg17
PG_PORT      := 55433
PG_DB        := beehub
PSQL         := docker exec -i $(PG_CONTAINER) psql -U postgres -d $(PG_DB)
VENV         := apps/api/.venv/bin

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: install-web ## Install backend and frontend dependencies
	cd apps/api && python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"

install-web: ## Install frontend dependencies
	cd apps/web && npm install

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
	@# Every migration applies here. 0004_storage.sql guards itself on whether
	@# the storage schema exists, so it is a no-op against plain Postgres.
	@for f in supabase/migrations/*.sql; do \
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

api: ## Run the API on :8000
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Run the frontend on :5173
	cd apps/web && npm run dev

worker: ## Run the ingestion worker (polls for uploads)
	cd apps/api && .venv/bin/python -m app.worker

worker-once: ## Process any queued uploads, then exit
	cd apps/api && .venv/bin/python -m app.worker --once

dev: ## Run api + worker + web together (ctrl-C stops all three)
	@echo "api    -> http://localhost:8000"
	@echo "web    -> http://localhost:5173"
	@echo "worker -> polling for uploads"
	@echo
	@# -l line-buffers sed, without which each stream's output is held in a
	@# 4KB block and the logs appear in bursts (or not at all).
	@# PYTHONUNBUFFERED does the same for the Python side.
	@trap 'kill 0' EXIT INT TERM; \
	  (cd apps/api && PYTHONUNBUFFERED=1 .venv/bin/uvicorn app.main:app --reload --port 8000 2>&1 | sed -l 's/^/[api]    /') & \
	  (cd apps/api && PYTHONUNBUFFERED=1 .venv/bin/python -m app.worker 2>&1 | sed -l 's/^/[worker] /') & \
	  (cd apps/web && npm run dev 2>&1 | sed -l 's/^/[web]    /') & \
	  wait
