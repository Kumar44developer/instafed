# ============================================================
#  Instafeed — developer shortcuts
#  Run `make help` to see everything.
# ============================================================
.DEFAULT_GOAL := help
.PHONY: help install dev test lint fmt coverage run demo docker-build docker-up docker-down poll clean

PYTHON ?= python
VENV   ?= .venv
BIN    := $(VENV)/Scripts/python.exe
PIP    := $(VENV)/Scripts/python.exe -m pip

ifeq ($(OS),Windows_NT)
else
BIN := $(VENV)/bin/python
PIP := $(VENV)/bin/python -m pip
endif

help: ## Show this help
	@echo "Instafeed — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV):
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV) ## Install runtime dependencies
	$(PIP) install -r requirements.txt

dev: $(VENV) ## Install runtime + development dependencies
	$(PIP) install -r requirements-dev.txt

test: $(VENV) ## Run the test-suite
	$(BIN) -m pytest -q

coverage: $(VENV) ## Run the test-suite with a coverage report
	$(BIN) -m pytest --cov=backend --cov-report=term-missing --cov-report=html

lint: $(VENV) ## Lint the codebase with ruff
	$(BIN) -m ruff check backend tests

fmt: $(VENV) ## Auto-format the codebase with ruff
	$(BIN) -m ruff format backend tests
	$(BIN) -m ruff check --fix backend tests

run: ## Start the development server with hot reload
	$(BIN) -m uvicorn backend.main:app --reload --port 8000

demo: ## Start the server in offline demo mode
	$(BIN) -m uvicorn backend.main:app --port 8000 --env-file .env

poll: ## Run a single poll cycle from the command line
	$(BIN) scripts/poll_once.py

docker-build: ## Build the production image
	docker build -t instafeed:latest .

docker-up: ## Start the app with docker compose
	docker compose up -d --build

docker-down: ## Stop the docker compose stack
	docker compose down

clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov coverage.xml
