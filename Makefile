.PHONY: help install dev test test-cov lint format build clean registry up down status examples check-pypi-deps publish-pypi bump-patch bump-minor bump-major release

PYTHON ?= python3
CONFIG ?= saas.pactown.yaml
README ?= README.md
SANDBOX ?= ./sandbox

BUMP2VERSION_PY := $(shell $(PYTHON) -c 'import os,sys; print(os.path.join(os.path.dirname(sys.executable),"bump2version"))')
ifneq (,$(wildcard $(BUMP2VERSION_PY)))
BUMP2VERSION := $(BUMP2VERSION_PY)
else
BUMP2VERSION := bump2version
endif

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install pactown package
	$(PYTHON) -m pip install -e .

dev: ## Install dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"

test: ## Run tests
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest tests/ -v

test-cov: ## Run tests with coverage
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest tests/ -v --cov=src/pactown --cov-report=term-missing

lint: ## Run linter
	$(PYTHON) -m ruff check src/ tests/

format: ## Format code
	$(PYTHON) -m ruff format src/ tests/

build: clean ## Build package
	@$(PYTHON) -c "import build" >/dev/null 2>&1 || (echo "Missing dependency: build. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install build)" && exit 1)
	$(PYTHON) -m build

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned all generated files"

# Registry commands
registry: ## Start local pactown registry
	pactown-registry --host 0.0.0.0 --port 8800

registry-bg: ## Start registry in background
	pactown-registry --host 0.0.0.0 --port 8800 &

# Ecosystem commands
up: ## Start all services from config (usage: make up CONFIG=path/to/config.yaml)
	pactown up $(CONFIG)

down: ## Stop all services
	pactown down $(CONFIG)

status: ## Show status of all services
	pactown status $(CONFIG)

validate: ## Validate ecosystem configuration
	pactown validate $(CONFIG)

graph: ## Show dependency graph
	pactown graph $(CONFIG)

# Development helpers
examples: ## Run example ecosystem
	pactown up examples/saas.pactown.yaml --dry-run

init: ## Initialize new pactown ecosystem
	pactown init

publish: ## Publish all modules to registry
	pactown publish $(CONFIG) --registry http://localhost:8800

pull: ## Pull dependencies from registry
	pactown pull $(CONFIG) --registry http://localhost:8800

check-pypi-deps: ## Check dependencies for building/publishing
	@$(PYTHON) -c "import build" >/dev/null 2>&1 || (echo "Missing dependency: build. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install build)" && exit 1)
	@$(PYTHON) -c "import twine" >/dev/null 2>&1 || (echo "Missing dependency: twine. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install twine)" && exit 1)
	@$(BUMP2VERSION) --help >/dev/null 2>&1 || (echo "Missing dependency: bump2version. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install bump2version)" && exit 1)

publish-pypi: ## Publish to PyPI production (uses ~/.pypirc credentials)
	@$(MAKE) check-pypi-deps
	@$(MAKE) bump-patch
	@$(MAKE) build
	$(PYTHON) -m twine upload dist/*

# Version management
version: ## Show current version
	@grep -m1 'version = ' pyproject.toml | cut -d'"' -f2

bump-patch: ## Bump patch version (0.1.0 → 0.1.1)
	$(BUMP2VERSION) patch --config-file .bumpversion.cfg --allow-dirty
	@echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)"

bump-minor: ## Bump minor version (0.1.0 → 0.2.0)
	$(BUMP2VERSION) minor --config-file .bumpversion.cfg --allow-dirty
	@echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)"

bump-major: ## Bump major version (0.1.0 → 1.0.0)
	$(BUMP2VERSION) major --config-file .bumpversion.cfg --allow-dirty
	@echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)"

release: publish-pypi ## Bump patch and publish