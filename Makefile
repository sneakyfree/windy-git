# The local gate IS the merge gate (G0.6).
# No decorative CI: a workflow that cannot run is deleted, not committed.

.PHONY: help dev check lint type test vocab migrate downgrade fmt

help:
	@echo "make dev       — app + gitea + postgres, seeded fixtures (G0.8)"
	@echo "make check     — THE GATE: lint + type + test + vocab + drift"
	@echo "make migrate   — alembic upgrade head"
	@echo "make fmt       — ruff format + fix"

dev:
	docker compose up -d
	@echo "api      http://localhost:8600/health/full"
	@echo "gitea    http://localhost:3000"

check: lint type vocab test
	@echo ""
	@echo "  ✓ gate passed"

lint:
	ruff check api scripts

type:
	mypy api/app --ignore-missing-imports

vocab:
	@python3 scripts/vocab_audit.py

test:
	pytest -q

fmt:
	ruff format api scripts
	ruff check --fix api scripts

migrate:
	alembic upgrade head

downgrade:
	alembic downgrade -1
