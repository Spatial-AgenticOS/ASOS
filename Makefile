.PHONY: install dev serve client docker docker-down test lint clean setup doctor

PYTHON ?= python3
PIP    ?= $(PYTHON) -m pip

# ── Tier 1: Quick start ──────────────────────────────────────

install:
	$(PIP) install -e "feral-core[llm]"
	@echo ""
	@echo "  Run: feral setup   (first-time configuration)"
	@echo "  Run: feral start   (brain + dashboard)"

setup:
	feral setup

# ── Tier 3: Full development environment ─────────────────────

dev: dev-brain dev-deps
	@echo ""
	@echo "  Brain deps installed with dev + llm extras."
	@echo "  Client deps installed."
	@echo ""
	@echo "  Start developing:"
	@echo "    make serve     — start the brain"
	@echo "    make client    — start the web UI (separate terminal)"
	@echo "    make test      — run tests"

dev-brain:
	$(PIP) install -e "feral-core[llm,dev]"

dev-deps:
	@if [ -d feral-client ] && command -v npm >/dev/null 2>&1; then \
		cd feral-client && npm install; \
	else \
		echo "  [skip] feral-client npm install (npm not found or directory missing)"; \
	fi

serve:
	feral serve

client:
	cd feral-client && npm run dev

# ── Docker (semi-manual tier) ────────────────────────────────

docker:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "  Created .env from .env.example — edit it with your API keys."; \
	fi
	docker compose up -d --build
	@echo ""
	@echo "  Brain:    http://localhost:9090"
	@echo "  Client:   http://localhost:3000"
	@echo "  Registry: http://localhost:8080"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Testing & quality ────────────────────────────────────────

test:
	cd feral-core && $(PYTHON) -m pytest tests/ -v

lint:
	cd feral-core && $(PYTHON) -m pytest tests/ -v --tb=short -q 2>/dev/null || true
	@echo "  (Full lint tooling planned — currently relies on pytest)"

# ── Utilities ────────────────────────────────────────────────

doctor:
	feral doctor

bundle-webui:
	bash scripts/build_webui.sh

clean:
	rm -rf feral-core/webui
	rm -rf feral-core/*.egg-info
	rm -rf feral-core/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help:
	@echo ""
	@echo "  FERAL Makefile"
	@echo "  ───────────────"
	@echo ""
	@echo "  Quick start:"
	@echo "    make install       pip install + prompt for setup"
	@echo "    make setup         run the guided setup wizard"
	@echo ""
	@echo "  Development:"
	@echo "    make dev           install all deps (brain + client)"
	@echo "    make serve         start the brain server"
	@echo "    make client        start the web UI dev server"
	@echo "    make test          run tests"
	@echo ""
	@echo "  Docker:"
	@echo "    make docker        build and start all services"
	@echo "    make docker-down   stop all services"
	@echo "    make docker-logs   tail service logs"
	@echo ""
	@echo "  Utilities:"
	@echo "    make doctor        check system health"
	@echo "    make bundle-webui  build client into feral-core/webui/"
	@echo "    make clean         remove build artifacts"
	@echo ""
