# Pactown 🏘️

Pactown Ecosystem Orchestrator - Build and manage decentralized microservice ecosystems from Markdown READMEs using markpact sandboxes and a centralized service registry.

## Contents

- [Metadata](#metadata)
- [Architecture](#architecture)
- [Interfaces](#interfaces)
- [Workflows](#workflows)
- [Quality Pipeline (`pyqual.yaml`)](#quality-pipeline-pyqualyaml)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Deployment](#deployment)
- [Environment Variables (`.env.example`)](#environment-variables-envexample)
- [Release Management (`goal.yaml`)](#release-management-goalyaml)
- [Makefile Targets](#makefile-targets)
- [Code Analysis](#code-analysis)
- [Call Graph](#call-graph)
- [Test Contracts](#test-contracts)
- [Intent](#intent)

## Metadata

- **name**: `pactown`
- **version**: `0.1.170`
- **python_requires**: `>=3.10`
- **license**: {'text': 'Apache-2.0'}
- **ai_model**: `openrouter/qwen/qwen3-coder-next`
- **ecosystem**: SUMD + DOQL + testql + taskfile
- **generated_from**: pyproject.toml, requirements-dev.txt, Makefile, testql(3), app.doql.less, pyqual.yaml, goal.yaml, .env.example, project/(3 analysis files)

## Architecture

```
SUMD (description) → DOQL/source (code) → taskfile (automation) → testql (verification)
```

### DOQL Application Declaration (`app.doql.less`)

```less markpact:doql path=app.doql.less
// LESS format — define @variables here as needed

app {
  name: pactown;
  version: 0.1.170;
}

dependencies {
  runtime: "markpact>=0.1.18, fastapi>=0.100.0, uvicorn>=0.20.0, httpx>=0.24.0, pyyaml>=6.0, rich>=13.0, click>=8.0, pydantic>=2.0, watchfiles>=0.20.0, python-dotenv>=1.0, nfo>=0.1.17";
  dev: "pytest>=8.2,<10, pytest-cov>=4.0, pytest-asyncio>=1.3,<2, ruff>=0.1, build, twine, bump2version>=1.0, goal>=2.1.0, costs>=0.1.20, pfix>=0.1.60";
}

entity[name="User"] {
  id: int!;
  name: string!;
  email: string!;
  created_at: datetime!;
}

entity[name="Stats"] {
  total_users: int!;
  active_services: int!;
  uptime_seconds: float!;
}

interface[type="api"] {
  type: rest;
  framework: fastapi;
}

interface[type="cli"] {
  framework: click;
}
interface[type="cli"] page[name="pactown"] {

}

workflow[name="install"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) -m pip install -e .;
}

workflow[name="dev"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) -m pip install -e ".[dev]";
}

workflow[name="ensure-test-deps"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) -m pip show pytest-asyncio >/dev/null 2>&1 || $(PYTHON) -m pip install pytest-asyncio;
}

workflow[name="test"] {
  trigger: manual;
  step-1: depend target=ensure-test-deps;
  step-2: depend target=test-full;
}

workflow[name="test-api"] {
  trigger: manual;
  step-1: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest -p anyio -p pytest_asyncio.plugin tests/test_runner_api.py tests/test_targets.py -q;
}

workflow[name="test-fast"] {
  trigger: manual;
  step-1: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest -p anyio -p pytest_asyncio.plugin tests/ --ignore=tests/test_ansible.py -q;
}

workflow[name="test-full"] {
  trigger: manual;
  step-1: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest -p anyio -p pytest_asyncio.plugin tests/ -q;
}

workflow[name="test-cov"] {
  trigger: manual;
  step-1: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src $(PYTHON) -m pytest -p anyio -p pytest_asyncio.plugin tests/ -q --cov=src/pactown --cov-report=term-missing;
}

workflow[name="lint"] {
  trigger: manual;
  step-1: run cmd=if $(PYTHON) -c "import ruff" >/dev/null 2>&1; then \;
  step-2: run cmd=$(PYTHON) -m ruff check src/ tests/; \;
  step-3: run cmd=elif command -v ruff >/dev/null 2>&1; then \;
  step-4: run cmd=ruff check src/ tests/; \;
  step-5: run cmd=elif command -v pipx >/dev/null 2>&1; then \;
  step-6: run cmd=pipx run ruff check src/ tests/; \;
  step-7: run cmd=else \;
  step-8: run cmd=echo "Missing dependency: ruff. Run: make dev (or install via pipx)."; \;
  step-9: run cmd=exit 1; \;
  step-10: run cmd=fi;
}

workflow[name="format"] {
  trigger: manual;
  step-1: run cmd=if $(PYTHON) -c "import ruff" >/dev/null 2>&1; then \;
  step-2: run cmd=$(PYTHON) -m ruff format src/ tests/; \;
  step-3: run cmd=elif command -v ruff >/dev/null 2>&1; then \;
  step-4: run cmd=ruff format src/ tests/; \;
  step-5: run cmd=elif command -v pipx >/dev/null 2>&1; then \;
  step-6: run cmd=pipx run ruff format src/ tests/; \;
  step-7: run cmd=else \;
  step-8: run cmd=echo "Missing dependency: ruff. Run: make dev (or install via pipx)."; \;
  step-9: run cmd=exit 1; \;
  step-10: run cmd=fi;
}

workflow[name="build"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) -c "import build" >/dev/null 2>&1 || (echo "Missing dependency: build. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install build)" && exit 1);
  step-2: run cmd=$(PYTHON) -m build;
}

workflow[name="clean"] {
  trigger: manual;
  step-1: run cmd=rm -rf dist/ build/ *.egg-info src/*.egg-info;
  step-2: run cmd=find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true;
  step-3: run cmd=find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true;
  step-4: run cmd=echo "Cleaned all generated files";
}

workflow[name="registry"] {
  trigger: manual;
  step-1: run cmd=pactown-registry --host 0.0.0.0 --port 8800;
}

workflow[name="registry-bg"] {
  trigger: manual;
  step-1: run cmd=pactown-registry --host 0.0.0.0 --port 8800 &;
}

workflow[name="up"] {
  trigger: manual;
  step-1: run cmd=pactown up $(CONFIG);
}

workflow[name="down"] {
  trigger: manual;
  step-1: run cmd=pactown down $(CONFIG);
}

workflow[name="status"] {
  trigger: manual;
  step-1: run cmd=pactown status $(CONFIG);
}

workflow[name="validate"] {
  trigger: manual;
  step-1: run cmd=pactown validate $(CONFIG);
}

workflow[name="graph"] {
  trigger: manual;
  step-1: run cmd=pactown graph $(CONFIG);
}

workflow[name="examples"] {
  trigger: manual;
  step-1: run cmd=pactown up examples/saas.pactown.yaml --dry-run;
}

workflow[name="init"] {
  trigger: manual;
  step-1: run cmd=pactown init;
}

workflow[name="publish"] {
  trigger: manual;
  step-1: run cmd=pactown publish $(CONFIG) --registry http://localhost:8800;
}

workflow[name="pull"] {
  trigger: manual;
  step-1: run cmd=pactown pull $(CONFIG) --registry http://localhost:8800;
}

workflow[name="check-pypi-deps"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) -c "import build" >/dev/null 2>&1 || (echo "Missing dependency: build. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install build)" && exit 1);
  step-2: run cmd=$(PYTHON) -c "import twine" >/dev/null 2>&1 || (echo "Missing dependency: twine. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install twine)" && exit 1);
  step-3: run cmd=$(BUMP2VERSION) --help >/dev/null 2>&1 || (echo "Missing dependency: bump2version. Run: $(PYTHON) -m pip install -e \".[dev]\" (or: $(PYTHON) -m pip install bump2version)" && exit 1);
}

workflow[name="publish-pypi"] {
  trigger: manual;
  step-1: run cmd=$(MAKE) check-pypi-deps;
  step-2: run cmd=$(MAKE) bump-patch;
  step-3: run cmd=$(MAKE) sync-pactown-com;
  step-4: run cmd=$(MAKE) build;
  step-5: run cmd=$(PYTHON) -m twine upload dist/*;
}

workflow[name="version"] {
  trigger: manual;
  step-1: run cmd=grep -m1 'version = ' pyproject.toml | cut -d'"' -f2;
}

workflow[name="bump-patch"] {
  trigger: manual;
  step-1: run cmd=$(BUMP2VERSION) patch --config-file .bumpversion.cfg --allow-dirty;
  step-2: run cmd=echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)";
}

workflow[name="bump-minor"] {
  trigger: manual;
  step-1: run cmd=$(BUMP2VERSION) minor --config-file .bumpversion.cfg --allow-dirty;
  step-2: run cmd=echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)";
}

workflow[name="bump-major"] {
  trigger: manual;
  step-1: run cmd=$(BUMP2VERSION) major --config-file .bumpversion.cfg --allow-dirty;
  step-2: run cmd=echo "Bumped to $$(grep -m1 'version = ' pyproject.toml | cut -d'"' -f2)";
}

workflow[name="release"] {
  trigger: manual;
  step-1: depend target=publish-pypi;
}

workflow[name="sync-pactown-com"] {
  trigger: manual;
  step-1: run cmd=$(PYTHON) tools/sync_pactown_com_dependency.py;
}

workflow[name="security"] {
  trigger: manual;
  step-1: depend target=security-sast;
  step-2: depend target=security-deps;
}

workflow[name="security-sast"] {
  trigger: manual;
  step-1: run cmd=echo "Running SAST analysis...";
  step-2: run cmd=if $(PYTHON) -c "import bandit" >/dev/null 2>&1; then \;
  step-3: run cmd=$(PYTHON) -m bandit -r src/ -ll -ii --skip B101 || true; \;
  step-4: run cmd=elif command -v bandit >/dev/null 2>&1; then \;
  step-5: run cmd=bandit -r src/ -ll -ii --skip B101 || true; \;
  step-6: run cmd=else \;
  step-7: run cmd=echo "[SKIP] bandit not installed. Run: $(PYTHON) -m pip install bandit"; \;
  step-8: run cmd=fi;
  step-9: run cmd=if command -v semgrep >/dev/null 2>&1; then \;
  step-10: run cmd=semgrep scan --config=p/python --config=p/owasp-top-ten src/ --error 2>/dev/null || \;
  step-11: run cmd=semgrep scan --config=auto src/ --error 2>/dev/null || \;
  step-12: run cmd=echo "[WARN] semgrep scan completed with findings"; \;
  step-13: run cmd=else \;
  step-14: run cmd=echo "[SKIP] semgrep not installed. Run: pip install semgrep (or pipx install semgrep)"; \;
  step-15: run cmd=fi;
}

workflow[name="security-deps"] {
  trigger: manual;
  step-1: run cmd=echo "Scanning dependencies for vulnerabilities...";
  step-2: run cmd=if $(PYTHON) -c "import pip_audit" >/dev/null 2>&1; then \;
  step-3: run cmd=$(PYTHON) -m pip_audit --desc on || true; \;
  step-4: run cmd=elif command -v pip-audit >/dev/null 2>&1; then \;
  step-5: run cmd=pip-audit --desc on || true; \;
  step-6: run cmd=else \;
  step-7: run cmd=echo "[SKIP] pip-audit not installed. Run: $(PYTHON) -m pip install pip-audit"; \;
  step-8: run cmd=fi;
}

workflow[name="security-secrets"] {
  trigger: manual;
  step-1: run cmd=echo "Scanning for secrets...";
  step-2: run cmd=if command -v gitleaks >/dev/null 2>&1; then \;
  step-3: run cmd=gitleaks detect --source . --verbose 2>/dev/null || echo "[WARN] Potential secrets found"; \;
  step-4: run cmd=else \;
  step-5: run cmd=echo "[SKIP] gitleaks not installed. Install: https://github.com/gitleaks/gitleaks#installing"; \;
  step-6: run cmd=fi;
}

workflow[name="security-all"] {
  trigger: manual;
  step-1: depend target=security;
  step-2: depend target=security-secrets;
}

workflow[name="artifacts-docker"] {
  trigger: manual;
  step-1: run cmd=if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \;
  step-2: run cmd=$(PYTHON) tools/validate_artifacts_docker.py \;
  step-3: run cmd=--root $(ARTIFACT_ROOT) --strict -v; \;
  step-4: run cmd=else \;
  step-5: run cmd=echo "ERROR: Docker not available"; exit 1; \;
  step-6: run cmd=fi;
}

workflow[name="artifacts-clean"] {
  trigger: manual;
  step-1: run cmd=echo "Cleaning $(ARTIFACT_ROOT)/ and bytecode caches...";
  step-2: run cmd=if [ -d "$(ARTIFACT_ROOT)" ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \;
  step-3: run cmd=docker run --rm -v "$$(cd $(ARTIFACT_ROOT) && pwd):/clean" ubuntu:22.04 \;
  step-4: run cmd=sh -c 'chmod -R 777 /clean/test-* 2>/dev/null; rm -rf /clean/test-*' 2>/dev/null; \;
  step-5: run cmd=fi;
  step-6: run cmd=rm -rf $(ARTIFACT_ROOT)/test-* 2>/dev/null || true;
  step-7: run cmd=find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true;
  step-8: run cmd=echo "Done – artifact directory cleaned.";
}

workflow[name="artifacts-quick"] {
  trigger: manual;
  step-1: run cmd=echo "";
  step-2: run cmd=echo "============================================================";
  step-3: run cmd=echo " STEP 1/3: Generating scaffold artifacts (18 frameworks)";
  step-4: run cmd=echo "============================================================";
  step-5: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-6: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-7: run cmd=$(ARTIFACT_TESTS)::TestRealScaffoldInPactown -v --tb=short;
  step-8: run cmd=echo "";
  step-9: run cmd=echo "============================================================";
  step-10: run cmd=echo " STEP 2/3: Validating artifact sizes (strict, no stubs)";
  step-11: run cmd=echo "============================================================";
  step-12: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-13: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-14: run cmd=$(ARTIFACT_TESTS)::TestArtifactSizeValidation -v --tb=short -s;
  step-15: run cmd=echo "";
  step-16: run cmd=echo "============================================================";
  step-17: run cmd=echo " STEP 3/3: Validating file correctness";
  step-18: run cmd=echo "============================================================";
  step-19: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-20: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-21: run cmd=$(ARTIFACT_TESTS)::TestGeneratedFileCorrectness -v --tb=short -s;
  step-22: run cmd=echo "";
  step-23: run cmd=echo "============================================================";
  step-24: run cmd=echo " DONE – quick validation passed";
  step-25: run cmd=echo "============================================================";
}

workflow[name="artifacts"] {
  trigger: manual;
  step-1: run cmd=echo "";
  step-2: run cmd=echo "============================================================";
  step-3: run cmd=echo " STEP 1/9: Generating scaffold artifacts (18 frameworks)";
  step-4: run cmd=echo "============================================================";
  step-5: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-6: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-7: run cmd=$(ARTIFACT_TESTS)::TestRealScaffoldInPactown -v --tb=short;
  step-8: run cmd=echo "";
  step-9: run cmd=echo "============================================================";
  step-10: run cmd=echo " STEP 2/9: Generating IaC artifacts (Docker)";
  step-11: run cmd=echo "============================================================";
  step-12: run cmd=if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \;
  step-13: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-14: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-15: run cmd=$(ARTIFACT_TESTS)::TestDockerIaCValidation::test_docker_iac_all_files_present_and_consistent \;
  step-16: run cmd=-v --tb=short; \;
  step-17: run cmd=else \;
  step-18: run cmd=echo "[SKIP] Docker not available – IaC scaffolds not generated"; \;
  step-19: run cmd=fi;
  step-20: run cmd=echo "";
  step-21: run cmd=echo "============================================================";
  step-22: run cmd=echo " STEP 3/9: Validating artifact sizes (strict, no stubs)";
  step-23: run cmd=echo "============================================================";
  step-24: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-25: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-26: run cmd=$(ARTIFACT_TESTS)::TestArtifactSizeValidation -v --tb=short -s;
  step-27: run cmd=echo "";
  step-28: run cmd=echo "============================================================";
  step-29: run cmd=echo " STEP 4/9: Validating file correctness (magic bytes,";
  step-30: run cmd=echo "           configs, syntax, schemas)";
  step-31: run cmd=echo "============================================================";
  step-32: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-33: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-34: run cmd=$(ARTIFACT_TESTS)::TestGeneratedFileCorrectness -v --tb=short -s;
  step-35: run cmd=echo "";
  step-36: run cmd=echo "============================================================";
  step-37: run cmd=echo " STEP 5/9: Docker native validation (every artifact in";
  step-38: run cmd=echo "           its native Docker container)";
  step-39: run cmd=echo "============================================================";
  step-40: run cmd=if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \;
  step-41: run cmd=$(PYTHON) tools/validate_artifacts_docker.py \;
  step-42: run cmd=--root $(ARTIFACT_ROOT) --strict -v; \;
  step-43: run cmd=else \;
  step-44: run cmd=echo "[SKIP] Docker not available – native validation skipped"; \;
  step-45: run cmd=fi;
  step-46: run cmd=echo "";
  step-47: run cmd=echo "============================================================";
  step-48: run cmd=echo " STEP 6/9: Docker platform tests (binary format,";
  step-49: run cmd=echo "           artifact execution, syntax checks)";
  step-50: run cmd=echo "============================================================";
  step-51: run cmd=if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \;
  step-52: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-53: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-54: run cmd=$(ARTIFACT_TESTS)::TestDockerArtifactSizeValidation \;
  step-55: run cmd=$(ARTIFACT_TESTS)::TestDockerBinaryFormatVerification \;
  step-56: run cmd=$(ARTIFACT_TESTS)::TestDockerArtifactExecution \;
  step-57: run cmd=$(ARTIFACT_TESTS)::TestDockerAutomatedExecution \;
  step-58: run cmd=$(ARTIFACT_TESTS)::TestDockerDockerfileValidation \;
  step-59: run cmd=-v --tb=short; \;
  step-60: run cmd=else \;
  step-61: run cmd=echo "[SKIP] Docker not available – platform validation skipped"; \;
  step-62: run cmd=fi;
  step-63: run cmd=echo "";
  step-64: run cmd=echo "============================================================";
  step-65: run cmd=echo " STEP 7/9: E2E build → deploy via Ansible";
  step-66: run cmd=echo "============================================================";
  step-67: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-68: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-69: run cmd=$(ARTIFACT_TESTS)::TestE2EBuildAndAnsibleDeploy \;
  step-70: run cmd=$(ARTIFACT_TESTS)::TestMultiPlatformArtifactsWithAnsible \;
  step-71: run cmd=-v --tb=short;
  step-72: run cmd=echo "";
  step-73: run cmd=echo "============================================================";
  step-74: run cmd=echo " STEP 8/9: Desktop + mobile artifact generation per OS";
  step-75: run cmd=echo "============================================================";
  step-76: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-77: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-78: run cmd=$(ARTIFACT_TESTS)::TestDesktopArtifactGeneration \;
  step-79: run cmd=$(ARTIFACT_TESTS)::TestMobileArtifactGeneration \;
  step-80: run cmd=$(ARTIFACT_TESTS)::TestAnsibleArtifactDistribution \;
  step-81: run cmd=-v --tb=short;
  step-82: run cmd=echo "";
  step-83: run cmd=echo "============================================================";
  step-84: run cmd=echo " STEP 9/9: Cross-platform matrix (framework × OS)";
  step-85: run cmd=echo "============================================================";
  step-86: run cmd=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \;
  step-87: run cmd=$(PYTHON) -m pytest -p pytest_asyncio.plugin \;
  step-88: run cmd=$(CROSS_PLATFORM_TESTS) -v --tb=short;
  step-89: run cmd=echo "";
  step-90: run cmd=echo "============================================================";
  step-91: run cmd=echo " ALL DONE – full artifact pipeline completed (9 steps)";
  step-92: run cmd=echo "============================================================";
}

deploy {
  target: docker;
}

environment[name="local"] {
  runtime: docker-compose;
  env_file: .env;
  python_version: >=3.10;
}
```

## Interfaces

### CLI Entry Points

- `pactown`
- `pactown-registry`
- `pactown-quadlet-api`
- `pactown-runner-api`

### testql Scenarios

#### `testql-scenarios/generated-api-integration.testql.toon.yaml`

```toon markpact:testql path=testql-scenarios/generated-api-integration.testql.toon.yaml
# SCENARIO: API Integration Tests
# TYPE: api
# GENERATED: true

CONFIG[3]{key, value}:
  base_url, http://localhost:8101
  timeout_ms, 30000
  retry_count, 3

API[4]{method, endpoint, expected_status}:
  GET, /health, 200
  GET, /api/v1/status, 200
  POST, /api/v1/test, 201
  GET, /api/v1/docs, 200

ASSERT[2]{field, operator, expected}:
  status, ==, ok
  response_time, <, 1000
```

#### `testql-scenarios/generated-api-smoke.testql.toon.yaml`

```toon markpact:testql path=testql-scenarios/generated-api-smoke.testql.toon.yaml
# SCENARIO: Auto-generated API Smoke Tests
# TYPE: api
# GENERATED: true
# DETECTORS: FastAPIDetector, FlaskDetector, ExpressDetector, ConfigEndpointDetector

CONFIG[5]{key, value}:
  base_url, http://localhost:8101
  timeout_ms, 10000
  retry_count, 3
  retry_backoff_ms, 1000
  detected_frameworks, FastAPIDetector, FlaskDetector, ExpressDetector, ConfigEndpointDetector

# Wait for service to be ready
WAIT 1000

# Health check
API GET /api/health 200
ASSERT_STATUS 200

# REST API Endpoints (1 unique)
API[1]{method, endpoint, expected_status}:
  GET, /, 200

# Capture useful values from responses for subsequent tests
# CAPTURE request_id FROM 'headers.x-request-id'
# CAPTURE session_token FROM 'body.token'

ASSERT[2]{field, operator, expected}:
  _status, <, 500
  _status, >=, 200

# Conditional flow for error handling
FLOW[2]{condition, action}:
  _status >= 500, LOG 'Server error detected'
  _status == 429, WAIT 2000  # Rate limit - wait and retry


# Summary by Framework:
#   fastapi: 1 endpoints
#   docker: 2 endpoints
```

#### `testql-scenarios/generated-from-pytests.testql.toon.yaml`

```toon markpact:testql path=testql-scenarios/generated-from-pytests.testql.toon.yaml
# SCENARIO: Auto-generated from Python Tests
# TYPE: integration
# GENERATED: true

CONFIG[2]{key, value}:
  base_url, ${api_url:-http://localhost:8101}
  timeout_ms, 10000

# Converted 4 API calls from pytest
API[4]{method, endpoint, expected_status}:
  POST, /generate/markdown, 200
  POST, /generate/container, 200
  POST, /generate/markdown, 200
  POST, /generate/container, 200

# Converted 420 assertions from pytest
ASSERT[420]{field, operator, expected}:
  endpoint.host, ==, "localhost"
  endpoint.port, ==, 8000
  limiter.check("user1"), ==, True
  endpoint.host, ==, "localhost"
  endpoint.port, ==, 8000
  limiter.check("user1"), ==, True
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.port, ==, 8001
  result.platform, ==, "web"
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.command, ==, "python -m http.server ${MARKPACT_PORT:-8000} --directory public"
  result.platform, ==, "desktop"
  result.platform, ==, "mobile"
  result.platform, ==, "web"
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.command, ==, "python -m http.server ${MARKPACT_PORT:-8000} --directory public"
  result.exit_code, ==, 0
  result.exit_code, ==, 0
  len(deps), ==, 1
  deps[0].name, ==, "database"
  deps[0].endpoint, ==, "http://localhost:8003"
  env.DB_URL, ==, "http://localhost:8003"
  env.PACTOWN_SERVICE_NAME, ==, "api"
  env.MARKPACT_PORT, ==, "8001"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "pyqt"
  target_cfg.app_name, ==, "DesktopGui"
  target_cfg.icon, ==, "icon.png"
  result.platform, ==, "desktop"
  result.framework, ==, "pyqt"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "tkinter"
  tauri.windows[0].width, ==, 1280
  tauri.windows[0].height, ==, 720
  tauri.bundle.identifier, ==, "com.test.taurichat"
  result.platform, ==, "desktop"
  result.framework, ==, "tauri"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "react-native"
  target_cfg.app_name, ==, "RNApp"
  target_cfg.app_id, ==, "com.test.rnapp"
  target_cfg.targets, ==, ["android"]
  name, ==, "RNApp"
  displayName, ==, "RNApp"
  displayName, ==, "My React Native App"
  result.platform, ==, "mobile"
  result.framework, ==, "react-native"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "flutter"
  result.platform, ==, "mobile"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "flutter"
  result.platform, ==, "desktop"
  infer_target_from_deps(.fastapi", "uvicorn), ==, TargetPlatform.WEB
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "hello-api"
  len(file_blocks), ==, 2  # main.py + index.html
  len(dep_blocks), ==, 1
  pkg.build.appId, ==, "com.pactown.hello-api"
  result.platform, ==, "desktop"
  result.framework, ==, "electron"
  infer_target_from_deps(.fastapi", "uvicorn), ==, TargetPlatform.WEB
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "hello-api"
  len(file_blocks), ==, 2  # main.py + index.html
  len(dep_blocks), ==, 1
  dep.name, ==, "api"
  dep.version, ==, "2.0.0"
  dep.endpoint, ==, "http://localhost:8001"
  dep.env_var, ==, "API_URL"
  service.name, ==, "web"
  service.readme, ==, "services/web/README.md"
  service.port, ==, 8002
  service.health_check, ==, "/health"
  len(service.depends_on), ==, 1
  service.depends_on[0].name, ==, "api"
  config.name, ==, "yaml-test"
  config.version, ==, "0.2.0"
  len(config.services), ==, 2
  config.services.web.depends_on[0].name, ==, "api"
  config.url, ==, "http://localhost:8800"
  config.namespace, ==, "default"
  cfg.pip_index_url, ==, "http://pactown/simple"
  cfg.npm_registry_url, ==, "http://npm.local"
  env.PIP_INDEX_URL, ==, "http://proxy/simple"
  env.PIP_EXTRA_INDEX_URL, ==, "http://proxy/simple"
  args.PIP_INDEX_URL, ==, "http://pypi-proxy/simple"
  args.APT_PROXY, ==, "http://apt-proxy:3142"
  args.NPM_CONFIG_REGISTRY, ==, "http://verdaccio:4873"
  len(blocks), ==, 5
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "Calculator"
  target_cfg.app_id, ==, "com.test.calc"
  name, ==, "Calculator"
  build.appId, ==, "com.test.calc"
  result.platform, ==, "desktop"
  result.framework, ==, "electron"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "pyinstaller"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "tauri"
  target_cfg.targets, ==, ["linux"
  package.productName, ==, "TauriApp"
  tauri.bundle.identifier, ==, "com.test.tauri"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "capacitor"
  target_cfg.targets, ==, ["android"
  target_cfg.app_id, ==, "com.test.todo"
  appName, ==, "TodoApp"
  appId, ==, "com.test.todo"
  result.platform, ==, "mobile"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "kivy"
  result.platform, ==, "web"
  cfg.target, ==, "desktop"
  cfg.framework, ==, "electron"
  cfg.build_targets, ==, ["linux"
  cfg.build_cmd, ==, "npx electron-builder"
  cfg.target, ==, "web"
  cfg.build_targets, ==, []
  cfg.build_targets, ==, ["android"
  d_cfg.platform, ==, TargetPlatform.DESKTOP
  m_cfg.platform, ==, TargetPlatform.MOBILE
  result.platform, ==, "desktop"
  captured.config_readme, ==, str(captured["readme_path"])
  captured.env, ==, {"PIP_INDEX_URL": "http://pypi-proxy.local/simple"}
  len(tasks), ==, 4
  health_task.ansible.builtin.uri.url, ==, "http://localhost:8000/health"
  health_task.retries, ==, 10
  result.endpoint, ==, "http://localhost:3000"
  result.service_name, ==, "electron-app"
  pb[0].name, ==, "Deploy electron-app via Pactown"
  container_task.community.docker.docker_container.name, ==, "electron-prod-electron-app"
  conf.tauri.bundle.identifier, ==, "com.pactown.tauri"
  pb[0].tasks[0].community.docker.docker_image.build.path, ==, str(sandbox)
  conf.appId, ==, "com.pactown.cap"
  conf.appName, ==, "cap-mobile"
  pkg.dependencies.@capacitor/android, ==, "^6.0.0"
  pkg.dependencies.@capacitor/ios, ==, "^6.0.0"
  result.endpoint, ==, "http://localhost:8100"
  app_data.name, ==, "rn-mobile"
  app_data.displayName, ==, "React Native Mobile"
  cap_conf.webDir, ==, "dist"
  teardown[0].tasks[0].community.docker.docker_container.state, ==, "absent"
  len(hosts), ==, 2
  conf.appId, ==, "com.test.cap"
  conf.appName, ==, "cap"
  conf.server.androidScheme, ==, "https"
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  len(tasks), ==, 4
  health_task.ansible.builtin.uri.url, ==, "http://localhost:8000/health"
  health_task.retries, ==, 10
  result.endpoint, ==, "http://localhost:3000"
  conf.appId, ==, "com.pactown.cap"
  conf.appName, ==, "cap-mobile"
  pkg.dependencies.@capacitor/android, ==, "^6.0.0"
  pkg.dependencies.@capacitor/ios, ==, "^6.0.0"
  result.endpoint, ==, "http://localhost:8100"
  conf.appId, ==, "com.test.cap"
  conf.appName, ==, "cap"
  conf.server.androidScheme, ==, "https"
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  normalize_host("https://www.Example.com:8443/path"), ==, "www.example.com"
  normalize_domain("https://www.Example.com:8443/path"), ==, "example.com"
  len(result.errors), ==, 0
  len(result.errors), ==, 0
  endpoint.url, ==, "http://127.0.0.1:8001"
  endpoint.health_url, ==, "http://127.0.0.1:8001/health"
  url, ==, f"http://127.0.0.1:{preferred}"
  env.DATABASE_URL, ==, f"http://127.0.0.1:{db_port}"
  env.DATABASE_HOST, ==, "127.0.0.1"
  env.DATABASE_PORT, ==, str(db_port)
  env.MARKPACT_PORT, ==, str(api_port)
  infer_target_from_deps(.fastapi), ==, TargetPlatform.WEB
  env_passed.SUPABASE_URL, ==, "https://example.supabase.co"
  env_passed.SUPABASE_ANON_KEY, ==, "secret-key"
  env_passed.PORT, ==, "8000"
  captured.pip_env.PIP_INDEX_URL, ==, "http://pypi-proxy.local/simple"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  pkg.main, ==, "main.js"
  package.productName, ==, "TauriDemo"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "capacitor"
  target_cfg.targets, ==, ["android"
  appName, ==, "TodoApp"
  appId, ==, "com.test.todo"
  webDir, ==, "dist"
  _find_web_assets_dir(tmp_path), ==, www
  _find_web_assets_dir(tmp_path), ==, build
  _find_web_assets_dir(tmp_path), ==, dist
  _find_web_assets_dir(tmp_path), ==, pub
  _find_web_assets_dir(tmp_path), ==, tmp_path
  _find_web_assets_dir(tmp_path), ==, tmp_path
  _find_web_assets_dir(tmp_path), ==, tmp_path / "www"
  _find_web_assets_dir(tmp_path), ==, tmp_path / "dist"
  _IMPORT_TO_APT.tkinter, ==, "python3-tk"
  _IMPORT_TO_APT._tkinter, ==, "python3-tk"
  calls, ==, []
  len(apt_install_calls), ==, 1
  infer_target_from_deps(.pyinstaller", "requests), ==, TargetPlatform.DESKTOP
  endpoint.host, ==, "localhost"
  endpoint.port, ==, 8000
  limiter.check("user1"), ==, True
  endpoint.host, ==, "localhost"
  endpoint.port, ==, 8000
  limiter.check("user1"), ==, True
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.port, ==, 8001
  result.platform, ==, "web"
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.command, ==, "python -m http.server ${MARKPACT_PORT:-8000} --directory public"
  result.platform, ==, "desktop"
  result.platform, ==, "mobile"
  result.platform, ==, "web"
  spec.spec.runtime.type, ==, "python"
  spec.spec.run.command, ==, "python -m http.server ${MARKPACT_PORT:-8000} --directory public"
  result.exit_code, ==, 0
  result.exit_code, ==, 0
  len(deps), ==, 1
  deps[0].name, ==, "database"
  deps[0].endpoint, ==, "http://localhost:8003"
  env.DB_URL, ==, "http://localhost:8003"
  env.PACTOWN_SERVICE_NAME, ==, "api"
  env.MARKPACT_PORT, ==, "8001"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "pyqt"
  target_cfg.app_name, ==, "DesktopGui"
  target_cfg.icon, ==, "icon.png"
  result.platform, ==, "desktop"
  result.framework, ==, "pyqt"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "tkinter"
  tauri.windows[0].width, ==, 1280
  tauri.windows[0].height, ==, 720
  tauri.bundle.identifier, ==, "com.test.taurichat"
  result.platform, ==, "desktop"
  result.framework, ==, "tauri"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "react-native"
  target_cfg.app_name, ==, "RNApp"
  target_cfg.app_id, ==, "com.test.rnapp"
  target_cfg.targets, ==, ["android"]
  name, ==, "RNApp"
  displayName, ==, "RNApp"
  displayName, ==, "My React Native App"
  result.platform, ==, "mobile"
  result.framework, ==, "react-native"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "flutter"
  result.platform, ==, "mobile"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "flutter"
  result.platform, ==, "desktop"
  infer_target_from_deps(.fastapi", "uvicorn), ==, TargetPlatform.WEB
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "hello-api"
  len(file_blocks), ==, 2  # main.py + index.html
  len(dep_blocks), ==, 1
  pkg.build.appId, ==, "com.pactown.hello-api"
  result.platform, ==, "desktop"
  result.framework, ==, "electron"
  infer_target_from_deps(.fastapi", "uvicorn), ==, TargetPlatform.WEB
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "hello-api"
  len(file_blocks), ==, 2  # main.py + index.html
  len(dep_blocks), ==, 1
  dep.name, ==, "api"
  dep.version, ==, "2.0.0"
  dep.endpoint, ==, "http://localhost:8001"
  dep.env_var, ==, "API_URL"
  service.name, ==, "web"
  service.readme, ==, "services/web/README.md"
  service.port, ==, 8002
  service.health_check, ==, "/health"
  len(service.depends_on), ==, 1
  service.depends_on[0].name, ==, "api"
  config.name, ==, "yaml-test"
  config.version, ==, "0.2.0"
  len(config.services), ==, 2
  config.services.web.depends_on[0].name, ==, "api"
  config.url, ==, "http://localhost:8800"
  config.namespace, ==, "default"
  cfg.pip_index_url, ==, "http://pactown/simple"
  cfg.npm_registry_url, ==, "http://npm.local"
  env.PIP_INDEX_URL, ==, "http://proxy/simple"
  env.PIP_EXTRA_INDEX_URL, ==, "http://proxy/simple"
  args.PIP_INDEX_URL, ==, "http://pypi-proxy/simple"
  args.APT_PROXY, ==, "http://apt-proxy:3142"
  args.NPM_CONFIG_REGISTRY, ==, "http://verdaccio:4873"
  len(blocks), ==, 5
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  target_cfg.app_name, ==, "Calculator"
  target_cfg.app_id, ==, "com.test.calc"
  name, ==, "Calculator"
  build.appId, ==, "com.test.calc"
  result.platform, ==, "desktop"
  result.framework, ==, "electron"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "pyinstaller"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "tauri"
  target_cfg.targets, ==, ["linux"
  package.productName, ==, "TauriApp"
  tauri.bundle.identifier, ==, "com.test.tauri"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "capacitor"
  target_cfg.targets, ==, ["android"
  target_cfg.app_id, ==, "com.test.todo"
  appName, ==, "TodoApp"
  appId, ==, "com.test.todo"
  result.platform, ==, "mobile"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "kivy"
  result.platform, ==, "web"
  cfg.target, ==, "desktop"
  cfg.framework, ==, "electron"
  cfg.build_targets, ==, ["linux"
  cfg.build_cmd, ==, "npx electron-builder"
  cfg.target, ==, "web"
  cfg.build_targets, ==, []
  cfg.build_targets, ==, ["android"
  d_cfg.platform, ==, TargetPlatform.DESKTOP
  m_cfg.platform, ==, TargetPlatform.MOBILE
  result.platform, ==, "desktop"
  captured.config_readme, ==, str(captured["readme_path"])
  captured.env, ==, {"PIP_INDEX_URL": "http://pypi-proxy.local/simple"}
  len(tasks), ==, 4
  health_task.ansible.builtin.uri.url, ==, "http://localhost:8000/health"
  health_task.retries, ==, 10
  result.endpoint, ==, "http://localhost:3000"
  result.service_name, ==, "electron-app"
  pb[0].name, ==, "Deploy electron-app via Pactown"
  container_task.community.docker.docker_container.name, ==, "electron-prod-electron-app"
  conf.tauri.bundle.identifier, ==, "com.pactown.tauri"
  pb[0].tasks[0].community.docker.docker_image.build.path, ==, str(sandbox)
  conf.appId, ==, "com.pactown.cap"
  conf.appName, ==, "cap-mobile"
  pkg.dependencies.@capacitor/android, ==, "^6.0.0"
  pkg.dependencies.@capacitor/ios, ==, "^6.0.0"
  result.endpoint, ==, "http://localhost:8100"
  app_data.name, ==, "rn-mobile"
  app_data.displayName, ==, "React Native Mobile"
  cap_conf.webDir, ==, "dist"
  teardown[0].tasks[0].community.docker.docker_container.state, ==, "absent"
  len(hosts), ==, 2
  conf.appId, ==, "com.test.cap"
  conf.appName, ==, "cap"
  conf.server.androidScheme, ==, "https"
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  len(tasks), ==, 4
  health_task.ansible.builtin.uri.url, ==, "http://localhost:8000/health"
  health_task.retries, ==, 10
  result.endpoint, ==, "http://localhost:3000"
  conf.appId, ==, "com.pactown.cap"
  conf.appName, ==, "cap-mobile"
  pkg.dependencies.@capacitor/android, ==, "^6.0.0"
  pkg.dependencies.@capacitor/ios, ==, "^6.0.0"
  result.endpoint, ==, "http://localhost:8100"
  conf.appId, ==, "com.test.cap"
  conf.appName, ==, "cap"
  conf.server.androidScheme, ==, "https"
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  r.returncode, ==, 0
  normalize_host("https://www.Example.com:8443/path"), ==, "www.example.com"
  normalize_domain("https://www.Example.com:8443/path"), ==, "example.com"
  len(result.errors), ==, 0
  len(result.errors), ==, 0
  endpoint.url, ==, "http://127.0.0.1:8001"
  endpoint.health_url, ==, "http://127.0.0.1:8001/health"
  url, ==, f"http://127.0.0.1:{preferred}"
  env.DATABASE_URL, ==, f"http://127.0.0.1:{db_port}"
  env.DATABASE_HOST, ==, "127.0.0.1"
  env.DATABASE_PORT, ==, str(db_port)
  env.MARKPACT_PORT, ==, str(api_port)
  infer_target_from_deps(.fastapi), ==, TargetPlatform.WEB
  env_passed.SUPABASE_URL, ==, "https://example.supabase.co"
  env_passed.SUPABASE_ANON_KEY, ==, "secret-key"
  env_passed.PORT, ==, "8000"
  captured.pip_env.PIP_INDEX_URL, ==, "http://pypi-proxy.local/simple"
  target_cfg.platform, ==, TargetPlatform.DESKTOP
  target_cfg.framework, ==, "electron"
  pkg.main, ==, "main.js"
  package.productName, ==, "TauriDemo"
  target_cfg.platform, ==, TargetPlatform.MOBILE
  target_cfg.framework, ==, "capacitor"
  target_cfg.targets, ==, ["android"
  appName, ==, "TodoApp"
  appId, ==, "com.test.todo"
  webDir, ==, "dist"
  _find_web_assets_dir(tmp_path), ==, www
  _find_web_assets_dir(tmp_path), ==, build
  _find_web_assets_dir(tmp_path), ==, dist
  _find_web_assets_dir(tmp_path), ==, pub
  _find_web_assets_dir(tmp_path), ==, tmp_path
  _find_web_assets_dir(tmp_path), ==, tmp_path
  _find_web_assets_dir(tmp_path), ==, tmp_path / "www"
  _find_web_assets_dir(tmp_path), ==, tmp_path / "dist"
  _IMPORT_TO_APT.tkinter, ==, "python3-tk"
  _IMPORT_TO_APT._tkinter, ==, "python3-tk"
  calls, ==, []
  len(apt_install_calls), ==, 1
  infer_target_from_deps(.pyinstaller", "requests), ==, TargetPlatform.DESKTOP
```

## Workflows

## Quality Pipeline (`pyqual.yaml`)

```yaml markpact:pyqual path=pyqual.yaml
pipeline:
  name: pactown-quality

  metrics:
    cc_max: 15
    critical_max: 0

  custom_tools:
    - name: code2llm_pactown
      binary: code2llm
      command: >-
        code2llm {workdir} -f toon -o ./project --no-chunk
        --exclude .git .venv .venv_test build dist __pycache__ .pytest_cache .code2llm_cache .benchmarks .mypy_cache .ruff_cache node_modules
      output: ""
      allow_failure: false

    - name: vallm_pactown
      binary: vallm
      command: >-
        vallm batch {workdir} --recursive --format toon --output ./project
        --exclude .git,.venv,.venv_test,build,dist,__pycache__,.pytest_cache,.code2llm_cache,.benchmarks,.mypy_cache,.ruff_cache,node_modules
      output: ""
      allow_failure: false

  stages:
    - name: analyze
      tool: code2llm_pactown
      optional: true
      timeout: 0

    - name: validate
      tool: vallm_pactown
      optional: true
      timeout: 0

    - name: lint
      tool: ruff
      optional: true

    - name: fix
      tool: prefact
      optional: true
      when: metrics_fail
      timeout: 900

    - name: test
      run: python3 -m pytest -p anyio -q
      when: always

  loop:
    max_iterations: 3
    on_fail: report

  env:
    LLM_MODEL: openrouter/qwen/qwen3-coder-next
```

## Configuration

```yaml
project:
  name: pactown
  version: 0.1.170
  env: local
```

## Dependencies

### Runtime

```text markpact:deps python
markpact>=0.1.18
fastapi>=0.100.0
uvicorn>=0.20.0
httpx>=0.24.0
pyyaml>=6.0
rich>=13.0
click>=8.0
pydantic>=2.0
watchfiles>=0.20.0
python-dotenv>=1.0
nfo>=0.1.17
```

### Development

```text markpact:deps python scope=dev
pytest>=8.2,<10
pytest-cov>=4.0
pytest-asyncio>=1.3,<2
ruff>=0.1
build
twine
bump2version>=1.0
goal>=2.1.0
costs>=0.1.20
pfix>=0.1.60
```

## Deployment

```bash markpact:run
pip install pactown

# development install
pip install -e .[dev]
```

### Requirements Files

#### `requirements-dev.txt`

- `pytest>=7.0`
- `pytest-asyncio==0.23.4`

## Environment Variables (`.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | `*(not set)*` | Required: OpenRouter API key (https://openrouter.ai/keys) |
| `LLM_MODEL` | `openrouter/qwen/qwen3-coder-next` | Model (default: openrouter/qwen/qwen3-coder-next) |
| `PFIX_AUTO_APPLY` | `true` | true = apply fixes without asking |
| `PFIX_AUTO_INSTALL_DEPS` | `true` | true = auto pip/uv install |
| `PFIX_AUTO_RESTART` | `false` | true = os.execv restart after fix |
| `PFIX_MAX_RETRIES` | `3` |  |
| `PFIX_DRY_RUN` | `false` |  |
| `PFIX_ENABLED` | `true` |  |
| `PFIX_GIT_COMMIT` | `false` | true = auto-commit fixes |
| `PFIX_GIT_PREFIX` | `pfix:` | commit message prefix |
| `PFIX_CREATE_BACKUPS` | `false` | false = disable .pfix_backups/ directory |

## Release Management (`goal.yaml`)

- **versioning**: `semver`
- **commits**: `conventional` scope=`pactown`
- **changelog**: `keep-a-changelog`
- **build strategies**: `python`, `nodejs`, `rust`
- **version files**: `VERSION`, `pyproject.toml:version`, `venv/lib/python3.13/site-packages/httpcore/__init__.py:__version__`

## Makefile Targets

- `BUMP2VERSION_PY`
- `BUMP2VERSION`
- `BUMP2VERSION`
- `help`
- `install`
- `dev`
- `ensure-test-deps`
- `test`
- `test-api`
- `test-fast`
- `test-full`
- `test-cov`
- `lint`
- `format`
- `build`
- `clean`
- `registry` — Registry commands
- `registry-bg`
- `up` — Ecosystem commands
- `down`
- `status`
- `validate`
- `graph`
- `examples` — Development helpers
- `init`
- `publish`
- `pull`
- `check-pypi-deps`
- `publish-pypi`
- `version` — Version management
- `bump-patch`
- `bump-minor`
- `bump-major`
- `release`
- `sync-pactown-com`
- `security` — Security targets
- `security-sast`
- `security-deps`
- `security-secrets`
- `security-all`
- `ARTIFACT_ROOT` — Artifact generation & validation
- `ARTIFACT_TESTS`
- `artifacts-docker`
- `artifacts-clean`
- `CROSS_PLATFORM_TESTS`
- `artifacts-quick`
- `artifacts`

## Code Analysis

### `project/map.toon.yaml`

```toon markpact:analysis path=project/map.toon.yaml
# pactown | 87f 40281L | python:84,shell:2,less:1 | 2026-06-06
# stats: 538 func | 278 cls | 87 mod | CC̄=3.8 | critical:28 | cycles:0
# alerts[5]: CC render_error_report_md=43; CC build_error_context=41; CC kill_process_on_port=25; CC test_full_desktop_markpact=20; CC test_self_heal_corrupted_cache=19
# hotspots[5]: create_runner_api fan=47; create_quadlet_api fan=40; create_app fan=27; build_error_context fan=26; test_self_heal_corrupted_cache fan=26
# evolution: baseline
# Keys: M=modules, D=details, i=imports, e=exports, c=classes, f=functions, m=methods
M[87]:
  app.doql.less,434
  examples/fast-start-demo/demo.py,121
  examples/security-policy/demo.py,106
  examples/user-isolation/demo.py,111
  project.sh,59
  src/pactown/__init__.py,241
  src/pactown/builders/__init__.py,19
  src/pactown/builders/base.py,156
  src/pactown/builders/desktop.py,666
  src/pactown/builders/mobile.py,472
  src/pactown/builders/registry.py,33
  src/pactown/builders/web.py,94
  src/pactown/cli.py,991
  src/pactown/config.py,253
  src/pactown/deploy/__init__.py,35
  src/pactown/deploy/ansible.py,587
  src/pactown/deploy/base.py,313
  src/pactown/deploy/compose.py,440
  src/pactown/deploy/docker.py,322
  src/pactown/deploy/kubernetes.py,474
  src/pactown/deploy/podman.py,422
  src/pactown/deploy/quadlet.py,1045
  src/pactown/deploy/quadlet_api.py,540
  src/pactown/deploy/quadlet_shell.py,565
  src/pactown/error_context.py,382
  src/pactown/events.py,1076
  src/pactown/fast_start.py,755
  src/pactown/generator.py,214
  src/pactown/iac.py,259
  src/pactown/llm.py,454
  src/pactown/markpact_blocks.py,70
  src/pactown/network.py,271
  src/pactown/nfo_config.py,211
  src/pactown/node_cache.py,259
  src/pactown/orchestrator.py,456
  src/pactown/parallel.py,272
  src/pactown/platform.py,147
  src/pactown/registry/__init__.py,13
  src/pactown/registry/client.py,261
  src/pactown/registry/models.py,158
  src/pactown/registry/server.py,218
  src/pactown/resolver.py,163
  src/pactown/runner_api.py,636
  src/pactown/runner_types.py,255
  src/pactown/sandbox_helpers.py,235
  src/pactown/sandbox_manager.py,1840
  src/pactown/security.py,691
  src/pactown/service_runner.py,1235
  src/pactown/targets.py,352
  src/pactown/user_isolation.py,464
  tests/__init__.py,2
  tests/conftest.py,46
  tests/test_ansible.py,7021
  tests/test_builders.py,2045
  tests/test_config.py,189
  tests/test_cross_platform.py,1391
  tests/test_deploy_dockerfile.py,190
  tests/test_deploy_optimizations.py,413
  tests/test_deploy_platforms.py,1310
  tests/test_e2e_build.py,585
  tests/test_e2e_build_extended.py,1397
  tests/test_e2e_deploy_desktop_mobile.py,864
  tests/test_electron_xvfb.py,246
  tests/test_iac_manifest.py,85
  tests/test_llm.py,312
  tests/test_markpact_blocks.py,108
  tests/test_markpact_target_blocks.py,242
  tests/test_network.py,162
  tests/test_node_cache.py,315
  tests/test_parallel.py,150
  tests/test_platform.py,57
  tests/test_quadlet_security.py,691
  tests/test_registry.py,154
  tests/test_resolver.py,143
  tests/test_runner_api.py,444
  tests/test_sandbox_manager_env_injection.py,62
  tests/test_sandbox_manager_node_deps.py,118
  tests/test_sandbox_manager_node_run_env.py,95
  tests/test_sandbox_manager_venv_heal.py,181
  tests/test_security.py,293
  tests/test_service_runner_fast_run_fallback.py,84
  tests/test_service_runner_validation.py,78
  tests/test_targets.py,170
  tests/test_user_isolation_manager.py,153
  tools/sync_pactown_com_dependency.py,90
  tools/validate_artifacts_docker.py,547
  tree.sh,2
D:
  examples/fast-start-demo/demo.py:
    e: main
    main()
  examples/security-policy/demo.py:
    e: main
    main()
  examples/user-isolation/demo.py:
    e: main
    main()
  src/pactown/__init__.py:
  src/pactown/builders/__init__.py:
  src/pactown/builders/base.py:
    e: BuildError,BuildResult,Builder
    BuildError:  # Raised when a build operation fails.
    BuildResult:  # Result of a build operation.
    Builder: platform_name(0),scaffold(1),build(1),_log(2),_run_shell(1)  # Abstract base for platform builders.
  src/pactown/builders/desktop.py:
    e: DesktopBuilder
    DesktopBuilder: platform_name(0),scaffold(1),build(1),_electron_already_scaffolded(1),_patch_electron_no_sandbox(3),_scaffold_electron(1),_move_to_dev_deps(2),_ensure_electron_dev_deps(1),_scaffold_tauri(1),_scaffold_python_desktop(1),_filter_electron_builder_cmd(1),_electron_builder_flags(1),_default_build_cmd(3),build_parallel(1),_generate_linux_launcher(3),_collect_artifacts(2)  # Builds desktop application artifacts from a markpact sandbox
  src/pactown/builders/mobile.py:
    e: _sanitize_java_package_id,MobileBuilder
    MobileBuilder: platform_name(0),scaffold(1),build(1),_scaffold_capacitor(1),_resolve_cap_web_dir(1),_scaffold_react_native(1),_scaffold_kivy(1),_ensure_cap_platforms(2),_default_build_cmd(2),_collect_artifacts(2)  # Builds mobile application artifacts from a markpact sandbox.
    _sanitize_java_package_id(raw)
  src/pactown/builders/registry.py:
    e: get_builder,get_builder_for_target
    get_builder(platform)
    get_builder_for_target(target)
  src/pactown/builders/web.py:
    e: WebBuilder
    WebBuilder: platform_name(0),scaffold(1),build(1)  # Web services don't produce build artifacts – they run as ser
  src/pactown/cli.py:
    e: is_lolm_available,get_llm_status,get_llm,set_llm_priority,reset_llm_provider,cli,up,down,status,validate,graph,init,publish,pull,scan,generate,build,targets,deploy,quadlet,quadlet_shell,quadlet_api,quadlet_generate,quadlet_init,quadlet_deploy,quadlet_list,quadlet_logs,llm,llm_status,llm_doctor,llm_priority,llm_reset,llm_test,main
    is_lolm_available()
    get_llm_status()
    get_llm()
    set_llm_priority(provider;priority)
    reset_llm_provider(provider)
    cli()
    up(config_path;dry_run;no_health;quiet;sequential;workers)
    down(config_path)
    status(config_path)
    validate(config_path)
    graph(config_path)
    init(name;output)
    publish(config_path;registry)
    pull(config_path;registry)
    scan(folder)
    generate(folder;name;output;base_port)
    build(readme_path;output;framework;target)
    targets(platform)
    deploy(config_path;output;production;kubernetes)
    quadlet()
    quadlet_shell(tenant;domain;system)
    quadlet_api(host;port;domain;tenant)
    quadlet_generate(markdown_path;output;domain;subdomain;tenant;tls)
    quadlet_init(domain;email;system)
    quadlet_deploy(markdown_path;domain;subdomain;tenant;tls;image)
    quadlet_list(tenant)
    quadlet_logs(service_name;tenant;lines)
    llm()
    llm_status()
    llm_doctor()
    llm_priority(provider;priority)
    llm_reset(provider)
    llm_test(provider;rotation)
    main(argv)
  src/pactown/config.py:
    e: load_config,DependencyConfig,ServiceConfig,RegistryConfig,CacheConfig,EcosystemConfig
    DependencyConfig: from_dict(2)  # Configuration for a service dependency.
    ServiceConfig: from_dict(3)  # Configuration for a single service in the ecosystem.
    RegistryConfig:  # Configuration for artifact registry.
    CacheConfig: from_env(2),_to_mapping(0),to_env(0),to_docker_build_args(0)
    EcosystemConfig: from_yaml(2),from_dict(3),to_dict(0),to_yaml(1)  # Configuration for a complete pactown ecosystem.
    load_config(path)
  src/pactown/deploy/__init__.py:
  src/pactown/deploy/ansible.py:
    e: generate_inventory,generate_deploy_playbook,generate_teardown_playbook,generate_build_playbook,AnsibleConfig,AnsibleBackend
    AnsibleConfig: for_local(1),for_remote(4)  # Extra Ansible-specific settings layered on top of Deployment
    AnsibleBackend: __init__(2),runtime_type(0),is_available(0),build_image(5),push_image(2),deploy(5),stop(1),logs(2),status(1),_write_playbook(2),_write_inventory(0),write_all(0),_run_playbook(1)  # Ansible-based deployment backend.
    generate_inventory()
    generate_deploy_playbook()
    generate_teardown_playbook()
    generate_build_playbook()
  src/pactown/deploy/base.py:
    e: RuntimeType,DeploymentMode,DeploymentConfig,DeploymentResult,DeploymentBackend
    RuntimeType:  # Container runtime types.
    DeploymentMode:  # Deployment environment modes.
    DeploymentConfig: for_production(1),for_development(1)  # Configuration for deployment.
    DeploymentResult:  # Result of a deployment operation.
    DeploymentBackend: __init__(1),runtime_type(0),is_available(0),build_image(5),push_image(2),deploy(5),stop(1),logs(2),status(1),generate_dockerfile(4),_create_dockerfile(3),_create_node_dockerfile(2)  # Abstract base class for deployment backends.
  src/pactown/deploy/compose.py:
    e: generate_compose_from_config,ComposeService,ComposeGenerator
    ComposeService:  # Represents a service in docker-compose.yaml.
    ComposeGenerator: __init__(3),generate(2),_create_service(2),_create_registry_service(0),generate_override(2),generate_production(2)  # Generate Docker Compose / Podman Compose files for pactown e
    generate_compose_from_config(config_path;output_dir;production)
  src/pactown/deploy/docker.py:
    e: DockerBackend
    DockerBackend: runtime_type(0),is_available(0),build_image(5),push_image(2),deploy(5),stop(1),logs(2),status(1)  # Docker container runtime backend.
  src/pactown/deploy/kubernetes.py:
    e: KubernetesBackend
    KubernetesBackend: __init__(2),runtime_type(0),_kubectl(0),is_available(0),build_image(5),push_image(2),deploy(5),stop(1),logs(2),status(1),generate_manifests(6),generate_hpa(4),save_manifests(3)  # Kubernetes deployment backend for production environments.
  src/pactown/deploy/podman.py:
    e: PodmanBackend
    PodmanBackend: runtime_type(0),is_available(0),build_image(5),push_image(2),deploy(5),stop(1),logs(2),status(1),generate_systemd_unit(2),create_pod(3)  # Podman container runtime backend.
  src/pactown/deploy/quadlet.py:
    e: sanitize_name,sanitize_env_value,sanitize_env_key,sanitize_path,sanitize_domain,sanitize_image,sanitize_health_check,validate_volume,check_dangerous_content,generate_traefik_quadlet,generate_markdown_service_quadlet,QuadletConfig,QuadletUnit,QuadletTemplates,QuadletBackend
    QuadletConfig: full_domain(0),systemd_path(0),tenant_path(0)  # Configuration for Quadlet deployment.
    QuadletUnit: filename(0),save(1)  # Represents a Quadlet unit file.
    QuadletTemplates: container(9),pod(5),network(6),volume(3)  # Template generator for Quadlet unit files.
    QuadletBackend: __init__(2),runtime_type(0),is_available(0),get_quadlet_version(0),build_image(5),push_image(2),generate_quadlet_files(7),deploy(5),stop(1),logs(2),status(1),_systemctl(2),list_services(0)  # Podman Quadlet deployment backend.
    sanitize_name(name)
    sanitize_env_value(value)
    sanitize_env_key(key)
    sanitize_path(path)
    sanitize_domain(domain)
    sanitize_image(image)
    sanitize_health_check(endpoint)
    validate_volume(volume)
    check_dangerous_content(content)
    generate_traefik_quadlet(config)
    generate_markdown_service_quadlet(markdown_path;config;image)
  src/pactown/deploy/quadlet_api.py:
    e: create_quadlet_api,run_api,DeploymentRequest,ContainerRequest,TraefikRequest,DeploymentResponse,QuadletFileResponse,ServiceStatus,ListServicesResponse
    DeploymentRequest:  # Request to deploy a Markdown service.
    ContainerRequest:  # Request to generate a container Quadlet file.
    TraefikRequest:  # Request to generate Traefik Quadlet files.
    DeploymentResponse:  # Response from deployment operation.
    QuadletFileResponse:  # Response containing generated Quadlet files.
    ServiceStatus:  # Service status information.
    ListServicesResponse:  # Response listing all services.
    create_quadlet_api(default_domain;default_tenant;user_mode)
    run_api(host;port;domain;tenant)
  src/pactown/deploy/quadlet_shell.py:
    e: run_shell,QuadletShell
    QuadletShell: __init__(3),do_status(1),do_config(1),do_generate(1),do_generate_container(1),do_generate_traefik(1),do_list(1),do_start(1),do_stop(1),do_restart(1),do_logs(1),do_reload(1),do_deploy(1),do_undeploy(1),do_init(1),do_export(1),do_help(1),do_quit(1),do_exit(1),do_EOF(1),default(1),emptyline(0)  # Interactive shell for Quadlet deployment management.
    run_shell(tenant_id;domain;user_mode)
  src/pactown/error_context.py:
    e: _truncate_text,extract_trace_ids,extract_file_paths,most_probable_file,_is_noise_path,_safe_resolve_under,_read_text_limited,build_error_context,render_error_report_md,ErrorContextConfig
    ErrorContextConfig:
    _truncate_text(value)
    extract_trace_ids(text)
    extract_file_paths(text)
    most_probable_file(paths)
    _is_noise_path(path_str)
    _safe_resolve_under(root;path_str)
    _read_text_limited(path)
    build_error_context()
    render_error_report_md(context)
  src/pactown/events.py:
    e: get_event_store,set_event_store,get_service_commands,get_service_queries,get_project_commands,get_project_queries,get_security_commands,get_security_queries,EventType,Event,EventStore,Aggregate,ServiceAggregate,ServiceCommands,ProjectCommands,SecurityCommands,ServiceQueries,ProjectQueries,SecurityQueries,Projection,ServiceStatusProjection
    EventType:  # Standard event types for service lifecycle.
    Event: to_dict(0),from_dict(2)  # Immutable event record.
    EventStore: __init__(1),_load_from_file(0),_save_to_file(0),append(1),_notify_subscribers(1),subscribe(2),subscribe_all(1),get_events(7),get_aggregate_history(1),count(1),get_current_sequence(0),clear(0)  # Append-only event store with subscription support.
    Aggregate: __init__(2),apply_event(1),load_from_history(1),raise_event(3),get_pending_events(0),clear_pending_events(0),load(3)  # Base class for event-sourced aggregates.
    ServiceAggregate: __init__(1),apply_event(1),to_dict(0)  # Event-sourced aggregate for service lifecycle.
    ServiceCommands: __init__(1),create_service(4),start_service(4),stop_service(2),record_error(4),record_health_check(4),delete_service(2)  # Command handlers for service operations.
    ProjectCommands: __init__(1),create_project(3),update_project(3),delete_project(2)  # Command handlers for project operations.
    SecurityCommands: __init__(1),record_security_check(5),record_rate_limit(3),record_anomaly(4)  # Command handlers for security events.
    ServiceQueries: __init__(1),get_service_history(1),get_recent_starts(1),get_recent_errors(1),get_recent_health_checks(2),get_stats(0),get_service_state(1),get_user_services(1)  # Query handlers for service read operations.
    ProjectQueries: __init__(1),get_project_history(1),get_recent_projects(2),get_stats(0)  # Query handlers for project read operations.
    SecurityQueries: __init__(1),get_recent_security_failures(1),get_user_security_history(2),get_rate_limit_hits(2),get_anomalies(2),get_stats(0)  # Query handlers for security read operations.
    Projection: __init__(1),apply(1),rebuild(0),catch_up(0)  # Base class for event projections.
    ServiceStatusProjection: __init__(1),apply(1),get_all(0),get_running(0),get_by_user(1),get(1)  # Projection maintaining current status of all services.
    get_event_store(persistence_path)
    set_event_store(store)
    get_service_commands(event_store)
    get_service_queries(event_store)
    get_project_commands(event_store)
    get_project_queries(event_store)
    get_security_commands(event_store)
    get_security_queries(event_store)
  src/pactown/fast_start.py:
    e: _heartbeat,_beat_every_s,_run_streamed,get_fast_starter,CachedVenv,PrewarmedSandbox,FastStartResult,DependencyCache,SandboxPool,FastServiceStarter,ParallelServiceRunner
    CachedVenv: is_valid(0)  # Cached virtual environment for a specific dependency set.
    PrewarmedSandbox:  # Pre-created sandbox ready for immediate use.
    FastStartResult:  # Result of fast startup.
    DependencyCache: __init__(3),_load_existing(0),_hash_deps(1),get_cached_venv(1),invalidate(1),save_existing_venv(3),create_and_cache(3),_cleanup_old(0),get_stats(0)  # Caches virtual environments by dependency hash.
    SandboxPool: __init__(3),_hash_deps(1),warm_pool(1),get_prewarmed(1),release(1)  # Pool of pre-warmed sandboxes for instant startup.
    FastServiceStarter: __init__(4),fast_create_sandbox(4),_write_files_parallel(2),_install_deps_direct(3),get_cache_stats(0)  # Optimized service starter with caching and parallel executio
    ParallelServiceRunner: __init__(2),run_parallel(2)  # Run multiple services in parallel with optimized startup.
    _heartbeat()
    _beat_every_s()
    _run_streamed(cmd)
    get_fast_starter(sandbox_root)
  src/pactown/generator.py:
    e: scan_readme,scan_folder,generate_config,print_scan_results
    scan_readme(readme_path)
    scan_folder(folder;recursive;pattern)
    generate_config(folder;name;base_port;output)
    print_scan_results(folder)
  src/pactown/iac.py:
    e: _runtime_type,_default_base_image,build_sandbox_spec,write_sandbox_manifest,build_single_service_compose,write_single_service_compose,write_sandbox_iac,SandboxIacOptions
    SandboxIacOptions: from_env(2)
    _runtime_type()
    _default_base_image()
    build_sandbox_spec()
    write_sandbox_manifest()
    build_single_service_compose()
    write_single_service_compose()
    write_sandbox_iac()
  src/pactown/llm.py:
    e: get_llm,is_lolm_available,get_lolm_info,generate,get_llm_status,set_provider_priority,reset_provider,PactownLLMError,LLMNotAvailableError,PactownLLM
    PactownLLMError:  # Base exception for Pactown LLM errors.
    LLMNotAvailableError:  # Raised when no LLM provider is available.
    PactownLLM: __init__(1),get_instance(2),set_instance(2),initialize(0),is_available(0),generate(4),generate_with_rotation(4),generate_with_fallback(4),get_status(0),get_provider_health(1),set_provider_priority(2),reset_provider(1),get_rotation_queue(0),on_rate_limit(1),on_rotation(1),on_provider_unavailable(1)  # Pactown LLM Manager with rotation and fallback support.
    get_llm(verbose)
    is_lolm_available()
    get_lolm_info()
    generate(prompt;system;max_tokens;with_rotation)
    get_llm_status()
    set_provider_priority(name;priority)
    reset_provider(name)
  src/pactown/markpact_blocks.py:
    e: extract_target_config,extract_build_cmd,extract_run_command
    extract_target_config(blocks)
    extract_build_cmd(blocks)
    extract_run_command(blocks)
  src/pactown/network.py:
    e: find_free_port,check_port,ServiceEndpoint,PortAllocator,ServiceRegistry
    ServiceEndpoint: url(0),health_url(0)  # Represents a running service's network endpoint.
    PortAllocator: __init__(2),is_port_free(1),allocate(1),release(1),release_all(0)  # Allocates free ports dynamically.
    ServiceRegistry: __init__(2),_load(0),_save(0),register(3),unregister(1),get(1),get_url(1),list_services(0),get_environment(2),clear(0)  # Local service registry for name-based service discovery.
    find_free_port(start;end)
    check_port(port)
  src/pactown/nfo_config.py:
    e: get_logger,setup_logging
    get_logger(name)
    setup_logging()
  src/pactown/node_cache.py:
    e: _sorted_deps,_copytree_hardlink,CachedNodeModules,NodeModulesCache
    CachedNodeModules: is_valid(0)  # A cached ``node_modules`` directory keyed by dependency hash
    NodeModulesCache: __init__(3),get(1),restore(3),save(3),invalidate(1),get_stats(0),_hash_pkg(1),_load_existing(0),_evict(0)  # Cache ``node_modules`` directories by ``package.json`` conte
    _sorted_deps(deps)
    _copytree_hardlink(src;dst)
  src/pactown/orchestrator.py:
    e: run_ecosystem,ServiceHealth,Orchestrator
    ServiceHealth:  # Health status of a service.
    Orchestrator: __init__(4),from_file(4),_get_readme_path(1),validate(0),start_service(1),start_all(3),_start_all_sequential(1),_start_all_parallel(2),_start_service_with_health(2),stop_service(1),stop_all(0),restart_service(1),check_health(1),_wait_for_health(2),print_status(0),print_graph(0),get_logs(2)  # Orchestrates the lifecycle of a pactown ecosystem.
    run_ecosystem(config_path;wait)
  src/pactown/parallel.py:
    e: run_parallel,run_in_dependency_waves,run_parallel_async,format_parallel_results,TaskResult,ParallelSandboxBuilder
    TaskResult:  # Result of a parallel task.
    ParallelSandboxBuilder: __init__(1),build_sandboxes(2)  # Build multiple sandboxes in parallel.
    run_parallel(tasks;max_workers;show_progress;description)
    run_in_dependency_waves(tasks;dependencies;max_workers;on_complete)
    run_parallel_async(tasks;max_concurrent)
    format_parallel_results(results)
  src/pactown/platform.py:
    e: coerce_subdomain_separator,normalize_host,normalize_domain,is_local_domain,build_origin,web_base_url,api_base_url,to_dns_label,parse_project_subdomain,build_project_subdomain,build_project_host,parse_project_host,build_service_subdomain,DomainConfig,ProjectHostParts
    DomainConfig: _normalize_domain(2),_normalize_separator(2)
    ProjectHostParts:
    coerce_subdomain_separator(value)
    normalize_host(value)
    normalize_domain(value)
    is_local_domain(domain)
    build_origin()
    web_base_url(domain;web_host_port)
    api_base_url(domain;api_host_port)
    to_dns_label(value)
    parse_project_subdomain(subdomain)
    build_project_subdomain(project_id;username)
    build_project_host(project_id;username)
    parse_project_host(host)
    build_service_subdomain(service_name;username)
  src/pactown/registry/__init__.py:
  src/pactown/registry/client.py:
    e: RegistryClient,AsyncRegistryClient
    RegistryClient: __init__(2),__enter__(0),__exit__(0),close(0),health(0),list_artifacts(2),get_artifact(2),get_version(3),get_readme(3),publish(8),pull(4),delete(2),list_namespaces(0)  # Client for interacting with pactown registry.
    AsyncRegistryClient: __init__(2),__aenter__(0),__aexit__(0),close(0),health(0),list_artifacts(2),get_readme(3),publish(7)  # Async client for pactown registry.
  src/pactown/registry/models.py:
    e: ArtifactVersion,Artifact,RegistryStorage
    ArtifactVersion: to_dict(0),from_dict(2)  # A specific version of an artifact.
    Artifact: full_name(0),add_version(1),get_version(1),to_dict(0),from_dict(2)  # An artifact in the registry (a markpact module).
    RegistryStorage: __init__(1),_load(0),_save(0),get(2),list(1),save_artifact(1),delete(2),search(1)  # File-based storage for registry artifacts.
  src/pactown/registry/server.py:
    e: create_app,main,PublishRequest,PublishResponse,ArtifactInfo,VersionInfo
    PublishRequest:
    PublishResponse:
    ArtifactInfo:
    VersionInfo:
    create_app(storage_path)
    main(host;port;storage;reload)
  src/pactown/resolver.py:
    e: ResolvedDependency,DependencyResolver
    ResolvedDependency:  # A resolved dependency with endpoint information.
    DependencyResolver: __init__(1),_build_graph(0),get_startup_order(0),get_shutdown_order(0),resolve_service_deps(1),get_environment(1),validate(0),print_graph(0)  # Resolves dependencies between services in an ecosystem.
  src/pactown/runner_api.py:
    e: _dns_label,_validate_service_id,_service_name_for,_validate_rel_path,_resolve_in_dir,create_runner_api,create_app,main,UserProfileRequest,RunRequest,StopRequest,ValidateRequest,SandboxPrepareRequest,SandboxFileWriteRequest,RunnerApiSettings,RunnerService
    UserProfileRequest:
    RunRequest:
    StopRequest:
    ValidateRequest:
    SandboxPrepareRequest:
    SandboxFileWriteRequest:
    RunnerApiSettings: __init__(0)
    RunnerService: __init__(0),_resolve_service_id(3),validate(1),_sandbox_path_for(1),list_sandbox_files(1),read_sandbox_file(3),write_sandbox_file(3),delete_sandbox_file(2),prepare_sandbox(3),run(0)
    _dns_label(value;fallback)
    _validate_service_id(service_id)
    _service_name_for(service_id)
    _validate_rel_path(path)
    _resolve_in_dir(root;rel)
    create_runner_api()
    create_app()
    main()
  src/pactown/runner_types.py:
    e: kill_process_on_port,ErrorCategory,DiagnosticInfo,AutoFixSuggestion,RunResult,EndpointTestResult,ValidationResult
    ErrorCategory:  # Categorized error types for better diagnostics.
    DiagnosticInfo: collect(2)  # Environment diagnostics for debugging.
    AutoFixSuggestion:  # Actionable suggestion to fix an error.
    RunResult: to_dict(0)  # Result of running a service with detailed diagnostics.
    EndpointTestResult:  # Result of testing an endpoint.
    ValidationResult:  # Result of validating markpact content.
    kill_process_on_port(port;force)
  src/pactown/sandbox_helpers.py:
    e: _ui_log_level,_should_emit_to_ui,_call_on_log,_filter_runtime_env,_sanitize_inherited_env,_escape_dotenv_value,_write_dotenv_file,_heartbeat,_beat_every_s,_path_debug
    _ui_log_level()
    _should_emit_to_ui(level)
    _call_on_log(on_log;msg;level)
    _filter_runtime_env(explicit_env)
    _sanitize_inherited_env(parent_env;explicit_env)
    _escape_dotenv_value(value)
    _write_dotenv_file(sandbox_path;env)
    _heartbeat()
    _beat_every_s()
    _path_debug(path)
  src/pactown/sandbox_manager.py:
    e: _sandbox_fallback_ids,_chown_sandbox_tree,_detect_web_preview_needed,_install_system_deps,_inject_electron_web_polyfill,_build_web_preview_cmd,_find_web_assets_dir,ServiceProcess,SandboxManager
    ServiceProcess: is_running(0)  # Represents a running service process.
    SandboxManager: _is_node_lang(1),_infer_node_project(0),_ensure_package_json(0),_install_node_deps(0),__init__(1),get_sandbox_path(1),create_sandbox(5),build_service(2),start_service(7),stop_service(2),stop_all(1),get_status(1),get_all_status(0),clean_sandbox(1),clean_all(0),create_sandboxes_parallel(3),start_services_parallel(3)  # Manages sandboxes for multiple services.
    _sandbox_fallback_ids()
    _chown_sandbox_tree(sandbox_path;uid;gid)
    _detect_web_preview_needed(expanded_cmd;target_cfg;full_env;sandbox_path)
    _install_system_deps(framework;log)
    _inject_electron_web_polyfill(serve_dir;target_cfg;log)
    _build_web_preview_cmd(sandbox_path;port;target_cfg;log)
    _find_web_assets_dir(sandbox_path)
  src/pactown/security.py:
    e: get_security_policy,set_security_policy,AnomalyType,UserTier,UserProfile,AnomalyEvent,AnomalyLogger,RateLimiter,ResourceMonitor,SecurityCheckResult,SecurityPolicy
    AnomalyType:  # Types of security anomalies.
    UserTier:  # User tier levels with different resource limits.
    UserProfile: from_tier(3),to_dict(0),from_dict(2)  # User profile with resource limits and permissions.
    AnomalyEvent: to_dict(0),to_log_line(0)  # Record of a security anomaly.
    AnomalyLogger: __init__(3),log(6),get_recent(1),get_by_user(2),get_by_type(2)  # Logs security anomalies for admin review.
    RateLimiter: __init__(2),_get_bucket(1),check(1),consume(1),get_wait_time(1)  # Token bucket rate limiter.
    ResourceMonitor: __init__(3),_get_cpu_percent(0),_get_memory_percent(0),check_overload(0),get_throttle_delay(0)  # Monitors system resources and detects overload.
    SecurityCheckResult: to_dict(0)  # Result of a security check.
    SecurityPolicy: __init__(5),set_user_profile(1),get_user_profile(1),register_service(2),unregister_service(2),get_user_service_count(1),get_services_started_last_hour(1),check_can_start_service(3),get_anomaly_summary(1)  # Main security policy enforcer for pactown.
    get_security_policy()
    set_security_policy(policy)
  src/pactown/service_runner.py:
    e: ServiceRunner
    ServiceRunner: __init__(6),validate_content(1),_extract_required_env_vars(1),_missing_required_env_vars(2),_prune_stale_user_services(2),run_from_content(10),_generate_suggestions(3),_wait_for_health(5),stop(1),get_status(1),list_services(0),test_endpoints(3),stop_all(0),fast_run(8),_quick_health_check(4),get_cache_stats(0)  # High-level service runner for markpact projects.
  src/pactown/targets.py:
    e: get_framework_meta,list_frameworks,_to_int,infer_target_from_deps,TargetPlatform,DesktopFramework,MobileFramework,WebFramework,FrameworkMeta,TargetConfig
    TargetPlatform:  # Target platform for a markpact project.
    DesktopFramework:  # Desktop application frameworks.
    MobileFramework:  # Mobile application frameworks.
    WebFramework:  # Web application frameworks (informational).
    FrameworkMeta:  # Metadata about a framework used for scaffolding and building
    TargetConfig: from_yaml_body(2),from_dict(2),framework_meta(0),is_web(0),is_desktop(0),is_mobile(0),is_buildable(0),needs_port(0),effective_build_targets(0)  # Parsed target configuration from a markpact:target block.
    get_framework_meta(name)
    list_frameworks(platform)
    _to_int(val)
    infer_target_from_deps(deps)
  src/pactown/user_isolation.py:
    e: _sanitize_gecos,get_isolation_manager,IsolatedUser,UserIsolationManager
    IsolatedUser: to_dict(0)  # Represents an isolated Linux user for sandbox execution.
    UserIsolationManager: __init__(2),can_isolate(0),_load_existing_users(0),_generate_username(1),get_or_create_user(1),get_user(1),get_sandbox_path(2),run_as_user(4),list_users(0),get_user_stats(1),export_user_data(2),import_user_data(2),delete_user(2)  # Manages isolated Linux users for sandbox execution.
    _sanitize_gecos(value)
    get_isolation_manager()
  tests/__init__.py:
  tests/conftest.py:
    e: async_test,anyio_backend
    async_test(fn)
    anyio_backend()
  tests/test_ansible.py:
    e: _deploy_config,test_runtime_type_ansible_exists,test_runtime_type_ansible_in_enum,_docker_available,_docker_run,_docker_run_script,_should_skip_artifact_scan,_classify_artifact_size,TestAnsibleConfig,TestGenerateInventory,TestGenerateDeployPlaybook,TestGenerateTeardownPlaybook,TestGenerateBuildPlaybook,TestAnsibleBackendDryRun,TestAnsibleBackendAvailability,TestAnsibleBackendRun,TestAnsibleBackendLogsStatus,TestPlaybookYamlContent,TestIntegrationWithDeploymentConfig,TestAnsibleDesktopIntegration,TestAnsibleMobileIntegration,TestE2EBuildAndAnsibleDeploy,TestDesktopArtifactGeneration,TestMobileArtifactGeneration,TestMultiPlatformArtifactsWithAnsible,TestScaffoldConfigCorrectness,TestBuildCommandGeneration,TestElectronNoSandboxPatch,TestElectronBuilderFlagFiltering,TestDesktopFlutterTkinterArtifacts,TestAnsibleArtifactDistribution,TestArtifactsInPactownSandboxRoot,TestRealScaffoldInPactown,TestDockerArtifactExecution,TestDockerDockerfileValidation,TestDockerIaCValidation,TestArtifactSizeValidation,TestDockerArtifactSizeValidation,TestDockerBinaryFormatVerification,TestDockerAutomatedExecution,TestGeneratedFileCorrectness
    TestAnsibleConfig: test_defaults(0),test_for_local(0),test_for_remote_single_host(0),test_for_remote_multiple_hosts(0),test_custom_extra_vars(0),test_galaxy_requirements(0),test_roles_path(0),test_verbosity_levels(0)
    TestGenerateInventory: test_single_remote_host(0),test_localhost_gets_local_connection(0),test_127_0_0_1_gets_local_connection(0),test_multiple_hosts(0),test_custom_group_name(0),test_ssh_key_path(0),test_no_ssh_key(0),test_local_connection_skips_ansible_connection_var(0),test_ssh_connection_sets_ansible_connection_var(0),test_yaml_serialisable(0)
    TestGenerateDeployPlaybook: test_basic_structure(0),test_pull_task(0),test_network_task(0),test_container_task_port_mapping(0),test_container_task_no_port_when_not_exposed(0),test_container_env(0),test_container_memory_limit(0),test_container_read_only_fs(0),test_container_no_new_privileges(0),test_container_drop_capabilities(0),test_healthcheck_tasks_present(0),test_no_healthcheck_when_none(0),test_container_healthcheck_params(0),test_become_settings(0),test_no_become(0),test_container_name_includes_namespace(0),test_restart_policy(0),test_yaml_serialisable(0)
    TestGenerateTeardownPlaybook: test_structure(0),test_container_name(0),test_stop_tag(0)
    TestGenerateBuildPlaybook: test_basic(0),test_with_build_args(0),test_no_build_args(0),test_build_tag(0)
    TestAnsibleBackendDryRun: _backend(1),test_runtime_type(1),test_deploy_writes_files(1),test_deploy_endpoint(1),test_deploy_no_endpoint_when_ports_not_exposed(1),test_stop_writes_teardown(1),test_build_image_writes_playbook(1),test_build_image_default_tag(1),test_push_image_writes_playbook(1),test_push_image_no_registry(1),test_logs_dry_run(1),test_status_dry_run(1),test_write_all(1),test_write_all_no_health_check(1)
    TestAnsibleBackendAvailability: test_available_when_ansible_installed(2),test_not_available_when_not_installed(2),test_not_available_on_timeout(2)
    TestAnsibleBackendRun: _backend(1),test_deploy_runs_ansible_playbook(2),test_deploy_failure(2),test_deploy_timeout(2),test_deploy_ansible_not_found(2),test_stop_runs_ansible_playbook(2),test_verbosity_flag(2),test_extra_vars_passed(2),test_build_image_non_dry_run(2),test_push_image_non_dry_run(2)
    TestAnsibleBackendLogsStatus: test_logs_calls_docker(2),test_status_running(2),test_status_not_found(2),test_logs_docker_not_available(2)
    TestPlaybookYamlContent: test_deploy_playbook_roundtrips(1),test_inventory_has_all_hosts(1),test_teardown_playbook_content(1)
    TestIntegrationWithDeploymentConfig: test_production_config(1),test_development_config(1)
    TestAnsibleDesktopIntegration: test_electron_build_and_deploy_playbook(1),test_tauri_build_scaffold_with_ansible_deployment(1),test_pyinstaller_scaffold_and_ansible_build_playbook(1),test_pyqt_scaffold_with_icon_and_ansible(1),test_electron_multi_platform_build_with_ansible_matrix(1)  # Test Ansible deployment of desktop apps built with DesktopBu
    TestAnsibleMobileIntegration: test_capacitor_scaffold_and_ansible_deployment(1),test_react_native_scaffold_with_ansible(1),test_flutter_scaffold_android_ios_with_ansible(1),test_kivy_buildozer_scaffold_with_ansible(1),test_capacitor_webdir_detection_with_ansible(1)  # Test Ansible deployment of mobile apps built with MobileBuil
    TestE2EBuildAndAnsibleDeploy: test_desktop_electron_full_workflow(1),test_mobile_capacitor_full_workflow(1),test_multi_service_ansible_deployment(1)  # End-to-end tests: build artifacts, then deploy via Ansible.
    TestDesktopArtifactGeneration: test_electron_linux_appimage_artifact(1),test_electron_windows_exe_artifact(1),test_electron_macos_dmg_artifact(1),test_electron_snap_artifact(1),test_electron_linux_launcher_artifacts(1),test_tauri_linux_appimage_artifact(1),test_tauri_deb_artifact(1),test_pyinstaller_linux_binary_artifact(1),test_pyinstaller_windows_exe_artifact(1),test_pyqt_multi_os_artifacts(1)  # Test correct artifact generation for desktop apps across dif
    TestMobileArtifactGeneration: test_capacitor_android_apk_artifact(1),test_capacitor_android_release_apk_artifact(1),test_capacitor_ios_ipa_artifact(1),test_capacitor_dual_platform_artifacts(1),test_react_native_android_apk_artifact(1),test_react_native_ios_ipa_artifact(1),test_flutter_android_apk_artifact(1),test_flutter_ios_ipa_artifact(1),test_kivy_android_apk_artifact(1),test_kivy_android_aab_artifact(1)  # Test correct artifact generation for mobile apps across diff
    TestMultiPlatformArtifactsWithAnsible: test_electron_all_platforms_artifacts(1),test_capacitor_android_ios_artifacts_with_ansible(1),test_artifact_paths_in_ansible_playbook(1),test_flutter_multi_platform_architecture_artifacts(1)  # Test artifact generation for multiple platforms with Ansible
    TestScaffoldConfigCorrectness: test_electron_package_json_build_targets_all_os(1),test_electron_package_json_app_id(1),test_electron_package_json_default_app_id(1),test_electron_main_js_has_no_sandbox(1),test_electron_main_js_window_dimensions(1),test_electron_dev_deps_pinned(1),test_electron_moves_electron_from_deps_to_dev_deps(1),test_tauri_conf_bundle_identifier(1),test_tauri_conf_window_size(1),test_tauri_conf_default_window_size(1),test_tauri_conf_product_name(1),test_pyinstaller_spec_content(1),test_pyinstaller_spec_no_icon_by_default(1),test_pyqt_spec_with_icon(1),test_tkinter_spec_generated(1),test_capacitor_config_json_fields(1),test_capacitor_scripts_in_package_json(1),test_capacitor_webdir_root_index(1),test_capacitor_webdir_build_dir(1),test_capacitor_webdir_www_dir(1),test_capacitor_plugin_version_pinning(1),test_react_native_app_json_display_name(1),test_react_native_app_json_default_display_name(1),test_kivy_buildozer_spec_fields(1),test_kivy_buildozer_spec_icon(1),test_kivy_buildozer_spec_no_icon(1)  # Verify scaffold generates correct config files for each fram
    TestBuildCommandGeneration: test_electron_default_build_cmd_linux(0),test_electron_default_build_cmd_no_targets(0),test_tauri_default_build_cmd(0),test_pyinstaller_default_build_cmd(0),test_pyqt_default_build_cmd(0),test_tkinter_default_build_cmd(0),test_flutter_desktop_default_build_cmd(0),test_flutter_desktop_macos_build_cmd(0),test_flutter_desktop_windows_build_cmd(0),test_unknown_framework_returns_empty(0),test_capacitor_android_build_cmd(0),test_capacitor_ios_build_cmd(0),test_react_native_android_build_cmd(0),test_react_native_ios_build_cmd(0),test_flutter_android_build_cmd(0),test_flutter_ios_build_cmd(0),test_kivy_android_build_cmd(0),test_kivy_ios_build_cmd(0)  # Verify correct build commands are generated for each framewo
    TestElectronNoSandboxPatch: test_patch_commonjs_require(1),test_patch_es_module_import(1),test_patch_app_whenready_fallback(1),test_patch_app_on_fallback(1),test_patch_ultimate_fallback_prepend(1),test_patch_skips_already_patched(1),test_patch_no_main_js(1)  # Test all 4 patterns of --no-sandbox injection into main.js.
    TestElectronBuilderFlagFiltering: test_filter_keeps_linux_flag(0),test_filter_strips_mac_on_non_darwin(0),test_filter_ensures_at_least_one_platform(0),test_electron_builder_flags_linux_target(0),test_electron_builder_flags_empty_defaults_linux(0),test_electron_builder_flags_no_duplicates(0)  # Test electron-builder flag filtering based on host OS.
    TestDesktopFlutterTkinterArtifacts: test_flutter_desktop_linux_artifacts(1),test_tkinter_dist_artifacts(1),test_tkinter_windows_artifact(1),test_unknown_framework_fallback_artifacts(1),test_mobile_unknown_framework_fallback(1)  # Test artifact collection for desktop Flutter and Tkinter bui
    TestAnsibleArtifactDistribution: test_ansible_deploy_with_electron_linux_artifacts(1),test_ansible_deploy_with_capacitor_android_artifacts(1),test_ansible_deploy_multi_os_electron_with_separate_inventories(1),test_ansible_deploy_kivy_with_buildozer_artifacts(1),test_ansible_deploy_tauri_with_multi_format_artifacts(1),test_ansible_deploy_react_native_dual_platform(1)  # Test Ansible playbooks correctly distribute artifacts per OS
    TestArtifactsInPactownSandboxRoot: test_sandbox_manager_uses_configured_root(0),test_env_sandbox_root_points_to_pactown(0),test_service_runner_default_root_from_env(0),test_electron_artifacts_inside_sandbox_root(0),test_capacitor_artifacts_inside_sandbox_root(0),test_tauri_artifacts_inside_sandbox_root(0),test_ansible_deploy_artifacts_from_sandbox_root(0),test_dotenv_pactown_sandbox_root_is_project_local(0)  # Verify that builders create artifacts inside the configured 
    TestRealScaffoldInPactown: _root(0),_svc_path(1),_make_elf(1),_make_pe(1),_make_zip_package(2),_make_apk(3),_make_ipa(3),_make_aab(3),_make_dmg(1),_make_deb(1),_make_snap(1),_make_msi(1),_make_so(1),_make_appimage(1),_write_artifact(2),test_root_matches_dotenv_config(0),test_pactown_dir_exists(0),test_real_electron_scaffold_and_artifacts(0),test_real_tauri_scaffold_and_artifacts(0),test_real_pyinstaller_scaffold_and_artifacts(0),test_real_pyqt_scaffold_and_artifacts(0),test_real_tkinter_scaffold_and_artifacts(0),test_real_flutter_desktop_scaffold_and_artifacts(0),test_real_capacitor_scaffold_and_artifacts(0),test_real_react_native_scaffold_and_artifacts(0),test_real_flutter_mobile_scaffold_and_artifacts(0),test_real_kivy_scaffold_and_artifacts(0),test_real_fastapi_scaffold_and_artifacts(0),test_real_flask_scaffold_and_artifacts(0),test_real_express_scaffold_and_artifacts(0),test_real_nextjs_scaffold_and_artifacts(0),test_real_react_spa_scaffold_and_artifacts(0),test_real_vue_scaffold_and_artifacts(0),test_all_framework_dirs_present(0),test_all_artifacts_are_inside_pactown(0)  # Run REAL scaffolds in .pactown/ (as configured by .env) and 
    TestDockerArtifactExecution: _root(0),test_docker_electron_package_json(0),test_docker_electron_main_js(0),test_docker_electron_artifacts_exist(0),test_docker_tauri_config(0),test_docker_tauri_bundle_artifacts(0),test_docker_pyinstaller_spec(0),test_docker_pyinstaller_artifacts(0),test_docker_pyqt_spec_and_artifacts(0),test_docker_tkinter_spec_and_artifacts(0),test_docker_flutter_desktop_bundle(0),test_docker_capacitor_config(0),test_docker_capacitor_apk_ipa(0),test_docker_react_native_config(0),test_docker_react_native_apk_ipa(0),test_docker_flutter_mobile_artifacts(0),test_docker_kivy_buildozer_spec(0),test_docker_kivy_apk_aab(0),test_docker_fastapi_syntax_and_structure(0),test_docker_flask_syntax_and_structure(0),test_docker_express_syntax_and_structure(0),test_docker_nextjs_config_and_pages(0),test_docker_react_spa_structure(0),test_docker_vue_structure(0),test_docker_all_frameworks_mounted(0),test_docker_artifact_count(0)  # Run each framework's artifacts inside an appropriate Docker 
    TestDockerDockerfileValidation: _root(0),test_docker_fastapi_dockerfile_valid(0),test_docker_flask_dockerfile_valid(0),test_docker_express_dockerfile_valid(0),test_docker_all_web_dockerfiles_have_required_instructions(0)  # Validate that Dockerfiles created for web frameworks parse c
    TestDockerIaCValidation: _root(0),_ensure_writable_dir(1),_setup_iac_sandboxes(0),test_docker_iac_python_manifest_valid_yaml(0),test_docker_iac_node_manifest_valid_yaml(0),test_docker_iac_python_dockerfile_structure(0),test_docker_iac_node_dockerfile_structure(0),test_docker_iac_python_compose_valid(0),test_docker_iac_node_compose_valid(0),test_docker_iac_all_files_present_and_consistent(0)  # Generate IaC artifacts via pactown.iac module and validate t
    TestArtifactSizeValidation: _root(0),test_electron_artifacts_proper_size(0),test_tauri_artifacts_proper_size(0),test_pyinstaller_artifacts_proper_size(0),test_mobile_apk_ipa_proper_size(0),test_flutter_desktop_artifacts_proper_size(0),test_web_build_output_proper_size(0),test_strict_no_stubs_or_undersized(0),test_min_sizes_cover_all_binary_extensions(0),test_artifact_size_report(0)  # Verify all generated artifacts have proper size (no stubs).
    TestDockerArtifactSizeValidation: _root(0),test_docker_no_stub_binaries(0),test_docker_electron_dist_sizes_all_above_threshold(0),test_docker_mobile_packages_all_above_threshold(0)  # Validate artifact sizes and file formats inside Docker conta
    TestDockerBinaryFormatVerification: _root(0),test_docker_electron_elf_headers(0),test_docker_pyinstaller_elf_and_pe(0),test_docker_flutter_desktop_elf_and_so(0),test_docker_tauri_bundle_formats(0),test_docker_mobile_zip_packages(0)  # Verify artifact binary format headers with `file` command in
    TestDockerAutomatedExecution: _root(0),test_docker_run_fastapi_syntax_check(0),test_docker_run_fastapi_import_check(0),test_docker_run_flask_syntax_check(0),test_docker_run_flask_import_check(0),test_docker_run_express_syntax_check(0),test_docker_run_nextjs_syntax_check(0),test_docker_run_react_build_output_valid(0),test_docker_run_vue_build_output_valid(0),test_docker_dockerfile_parseable(0),test_docker_electron_run_sh_syntax(0)  # Actually run / syntax-check source code inside Docker contai
    TestGeneratedFileCorrectness: _root(0),test_elf_binaries_have_valid_header(0),test_pe_executables_have_mz_header(0),test_zip_packages_have_pk_magic(0),test_snap_has_squashfs_magic(0),test_msi_has_ole_magic(0),test_deb_has_ar_magic(0),test_dmg_has_udif_trailer(0),test_apk_contains_android_manifest(0),test_apk_manifest_is_valid_xml(0),test_ipa_contains_payload(0),test_aab_contains_bundle_config(0),test_all_json_files_parseable(0),test_package_json_has_required_fields(0),test_package_json_scripts_section(0),test_tauri_conf_json_schema(0),test_capacitor_config_json_schema(0),test_electron_package_json_build_config(0),test_react_native_app_json(0),test_all_yaml_files_parseable(0),test_docker_compose_has_services(0),test_docker_compose_healthcheck(0),test_pactown_sandbox_yaml_schema(0),test_all_python_files_valid_syntax(0),test_fastapi_main_has_app_and_health(0),test_flask_app_has_app_and_health(0),test_flask_wsgi_has_import(0),test_all_js_files_not_empty(0),test_express_index_has_routes(0),test_electron_main_js_structure(0),test_nextjs_pages_structure(0),test_nextjs_api_health_endpoint(0),test_vue_app_has_template(0),test_vue_main_js_creates_app(0),test_react_jsx_has_component(0),test_react_main_jsx_renders_root(0),test_html_files_have_valid_structure(0),test_dist_html_references_assets(0),test_css_files_have_style_rules(0),test_all_dockerfiles_have_from_and_cmd(0),test_dockerfiles_valid_instructions(0),test_dockerfiles_use_non_root_user(0),test_dockerfiles_have_healthcheck(0),test_requirements_txt_valid(0),test_requirements_match_framework(0),test_pyinstaller_spec_files_valid(0),test_pyinstaller_spec_references_main(0),test_buildozer_spec_valid(0),test_shell_scripts_have_shebang(0),test_vite_configs_define_plugin(0),test_build_outputs_match_source(0),test_web_dist_has_js_and_css_assets(0),test_all_services_have_metadata_or_build_config(0),test_correctness_report(0)  # Validate content correctness of all generated artifact files
    _deploy_config()
    test_runtime_type_ansible_exists()
    test_runtime_type_ansible_in_enum()
    _docker_available()
    _docker_run(image;mount_src;mount_dst;cmd;timeout)
    _docker_run_script(image;mount_src;mount_dst;script;timeout;retries)
    _should_skip_artifact_scan(path)
    _classify_artifact_size(path;min_sizes)
  tests/test_builders.py:
    e: test_get_builder_web,test_get_builder_desktop,test_get_builder_mobile,test_get_builder_for_target_none_defaults_to_web,test_get_builder_for_target_desktop,test_desktop_scaffold_electron,test_desktop_scaffold_electron_existing_package_json,test_desktop_scaffold_electron_merges_main_into_minimal_package_json,test_desktop_scaffold_electron_does_not_overwrite_existing_main,test_desktop_scaffold_tauri,test_desktop_scaffold_pyinstaller,test_sanitize_java_package_id_clean,test_sanitize_java_package_id_dashes,test_sanitize_java_package_id_leading_digit,test_sanitize_java_package_id_special_chars,test_sanitize_java_package_id_empty_segments,test_sanitize_java_package_id_fallback,test_mobile_scaffold_capacitor,test_mobile_scaffold_capacitor_sanitizes_dashed_appid,test_mobile_scaffold_capacitor_no_bundled_web_runtime,test_mobile_scaffold_capacitor_webdir_root,test_mobile_scaffold_capacitor_webdir_dist,test_mobile_scaffold_capacitor_webdir_www,test_mobile_scaffold_capacitor_ios_target,test_mobile_scaffold_capacitor_preserves_existing_deps,test_mobile_scaffold_capacitor_pins_latest_to_6x,test_mobile_scaffold_capacitor_migrates_storage_to_preferences,test_mobile_scaffold_capacitor_pins_ios_latest_to_6x,test_mobile_scaffold_capacitor_overrides_incompatible_platform_versions,test_mobile_scaffold_capacitor_updates_webdir_in_existing_config,test_mobile_scaffold_kivy,test_web_builder_scaffold_noop,test_web_builder_build_no_cmd,test_patch_no_sandbox_user_provided_main_js,test_patch_no_sandbox_already_patched,test_patch_no_sandbox_scaffolded_default,test_patch_no_sandbox_desktop_notes_main_js,test_patch_no_sandbox_no_main_js,test_patch_no_sandbox_double_quotes,test_patch_no_sandbox_es_module_single_quotes,test_patch_no_sandbox_es_module_double_quotes,test_patch_no_sandbox_ultimate_fallback,test_generate_linux_launcher_creates_files,test_generate_linux_launcher_no_dist,test_generate_linux_launcher_no_appimage,test_build_result_defaults,test_mobile_scaffold_capacitor_updates_plugin_versions,test_desktop_scaffold_tauri_window_dimensions,test_desktop_scaffold_tauri_default_dimensions,test_desktop_scaffold_tauri_does_not_overwrite_existing_config,test_desktop_scaffold_tauri_bundle_identifier,test_desktop_scaffold_pyqt,test_desktop_scaffold_pyqt_with_icon,test_desktop_scaffold_tkinter,test_desktop_scaffold_tkinter_does_not_overwrite_existing_spec,test_desktop_scaffold_flutter_desktop_noop,test_desktop_scaffold_unknown_framework_noop,test_electron_builder_flags_linux_only,test_electron_builder_flags_empty_defaults_to_linux,test_electron_builder_flags_none_defaults_to_linux,test_electron_builder_flags_windows_skipped_on_linux_no_wine,test_electron_builder_flags_windows_allowed_with_wine,test_electron_builder_flags_mac_skipped_on_linux,test_electron_builder_flags_mac_allowed_on_darwin,test_electron_builder_flags_windows_on_windows,test_electron_builder_flags_deduplicates,test_electron_builder_flags_aliases,test_filter_electron_builder_cmd_strips_windows_on_linux,test_filter_electron_builder_cmd_ensures_at_least_one_platform,test_desktop_default_build_cmd_electron_linux,test_desktop_default_build_cmd_electron_multi_target,test_desktop_default_build_cmd_tauri,test_desktop_default_build_cmd_pyinstaller,test_desktop_default_build_cmd_tkinter,test_desktop_default_build_cmd_pyqt,test_desktop_default_build_cmd_flutter_linux,test_desktop_default_build_cmd_flutter_windows,test_desktop_default_build_cmd_flutter_macos,test_desktop_default_build_cmd_unknown_framework,test_desktop_collect_artifacts_electron_appimage,test_desktop_collect_artifacts_electron_dmg,test_desktop_collect_artifacts_electron_snap,test_desktop_collect_artifacts_electron_run_sh,test_desktop_collect_artifacts_tauri,test_desktop_collect_artifacts_pyinstaller,test_desktop_collect_artifacts_pyqt,test_desktop_collect_artifacts_tkinter,test_desktop_collect_artifacts_flutter,test_desktop_collect_artifacts_empty,test_desktop_collect_artifacts_unknown_framework_fallback,test_desktop_scaffold_electron_build_targets,test_desktop_scaffold_electron_move_electron_to_dev_deps,test_desktop_scaffold_electron_ensure_dev_deps_added,test_desktop_build_no_cmd_returns_failure,test_mobile_scaffold_react_native,test_mobile_scaffold_react_native_default_display_name,test_mobile_scaffold_react_native_does_not_overwrite,test_mobile_scaffold_kivy_app_id,test_mobile_scaffold_kivy_no_fullscreen,test_mobile_scaffold_kivy_does_not_overwrite,test_mobile_scaffold_kivy_has_required_sections,test_mobile_scaffold_flutter_noop,test_mobile_scaffold_unknown_framework_noop,test_mobile_capacitor_webdir_priority_dist_over_www,test_mobile_capacitor_webdir_priority_build,test_mobile_capacitor_webdir_priority_public,test_mobile_capacitor_webdir_no_index_defaults_to_dist,test_mobile_default_build_cmd_capacitor_android,test_mobile_default_build_cmd_capacitor_ios,test_mobile_default_build_cmd_react_native_android,test_mobile_default_build_cmd_react_native_ios,test_mobile_default_build_cmd_flutter_android,test_mobile_default_build_cmd_flutter_ios,test_mobile_default_build_cmd_kivy_android,test_mobile_default_build_cmd_kivy_ios,test_mobile_default_build_cmd_unknown_framework,test_mobile_default_build_cmd_empty_targets_defaults_android,test_mobile_collect_artifacts_capacitor_apk,test_mobile_collect_artifacts_capacitor_ipa,test_mobile_collect_artifacts_capacitor_both,test_mobile_collect_artifacts_react_native_apk,test_mobile_collect_artifacts_react_native_ipa,test_mobile_collect_artifacts_flutter_apk,test_mobile_collect_artifacts_flutter_ipa,test_mobile_collect_artifacts_kivy_apk,test_mobile_collect_artifacts_kivy_aab,test_mobile_collect_artifacts_empty,test_mobile_collect_artifacts_unknown_framework_fallback,test_mobile_build_no_cmd_returns_failure,test_mobile_ensure_cap_platforms_skips_existing_dir,test_mobile_ensure_cap_platforms_runs_cap_add,test_mobile_ensure_cap_platforms_multiple_targets,test_mobile_ensure_cap_platforms_partial_existing,test_mobile_build_capacitor_calls_ensure_platforms,test_web_builder_platform_name,test_web_builder_scaffold_multiple_frameworks,test_web_builder_build_result_structure,test_build_result_all_fields,test_build_result_failure,test_target_config_from_dict_desktop_electron,test_target_config_from_dict_mobile_capacitor,test_target_config_from_dict_mobile_react_native,test_target_config_from_dict_mobile_flutter,test_target_config_from_dict_mobile_kivy,test_target_config_from_dict_desktop_tauri,test_target_config_from_dict_desktop_pyinstaller,test_target_config_from_dict_desktop_pyqt,test_target_config_from_dict_desktop_tkinter,test_target_config_from_dict_web_default,test_target_config_from_dict_unknown_platform_defaults_web,test_target_config_from_dict_targets_as_csv_string,test_target_config_from_dict_extra_keys_preserved,test_target_config_from_yaml_body,test_target_config_from_yaml_body_invalid,test_effective_build_targets_desktop_explicit,test_effective_build_targets_desktop_default,test_effective_build_targets_mobile_explicit,test_effective_build_targets_mobile_default,test_effective_build_targets_web_empty,test_target_config_framework_meta_electron,test_target_config_framework_meta_capacitor,test_target_config_framework_meta_pyinstaller,test_target_config_framework_meta_none,test_framework_registry_has_all_desktop_frameworks,test_framework_registry_has_all_mobile_frameworks,test_framework_registry_desktop_platforms,test_framework_registry_mobile_platforms,test_framework_registry_all_have_build_cmd,test_framework_registry_all_have_artifact_patterns,test_framework_registry_node_frameworks,test_framework_registry_python_frameworks,test_get_framework_meta_case_insensitive,test_get_framework_meta_unknown,test_list_frameworks_all,test_list_frameworks_desktop_only,test_list_frameworks_mobile_only,test_infer_target_electron,test_infer_target_tauri,test_infer_target_pyinstaller,test_infer_target_pyqt,test_infer_target_tkinter,test_infer_target_capacitor,test_infer_target_react_native,test_infer_target_expo,test_infer_target_buildozer,test_infer_target_flutter,test_infer_target_web_default,test_infer_target_empty_deps,test_infer_target_mobile_over_desktop_when_both_hinted,test_get_builder_for_target_mobile_capacitor,test_get_builder_for_target_mobile_react_native,test_get_builder_for_target_mobile_flutter,test_get_builder_for_target_mobile_kivy,test_get_builder_for_target_desktop_electron,test_get_builder_for_target_desktop_tauri,test_get_builder_for_target_desktop_pyinstaller,test_get_builder_for_target_desktop_pyqt,test_get_builder_for_target_desktop_tkinter,test_get_builder_for_target_web_fastapi
    test_get_builder_web()
    test_get_builder_desktop()
    test_get_builder_mobile()
    test_get_builder_for_target_none_defaults_to_web()
    test_get_builder_for_target_desktop()
    test_desktop_scaffold_electron(tmp_path)
    test_desktop_scaffold_electron_existing_package_json(tmp_path)
    test_desktop_scaffold_electron_merges_main_into_minimal_package_json(tmp_path)
    test_desktop_scaffold_electron_does_not_overwrite_existing_main(tmp_path)
    test_desktop_scaffold_tauri(tmp_path)
    test_desktop_scaffold_pyinstaller(tmp_path)
    test_sanitize_java_package_id_clean()
    test_sanitize_java_package_id_dashes()
    test_sanitize_java_package_id_leading_digit()
    test_sanitize_java_package_id_special_chars()
    test_sanitize_java_package_id_empty_segments()
    test_sanitize_java_package_id_fallback()
    test_mobile_scaffold_capacitor(tmp_path)
    test_mobile_scaffold_capacitor_sanitizes_dashed_appid(tmp_path)
    test_mobile_scaffold_capacitor_no_bundled_web_runtime(tmp_path)
    test_mobile_scaffold_capacitor_webdir_root(tmp_path)
    test_mobile_scaffold_capacitor_webdir_dist(tmp_path)
    test_mobile_scaffold_capacitor_webdir_www(tmp_path)
    test_mobile_scaffold_capacitor_ios_target(tmp_path)
    test_mobile_scaffold_capacitor_preserves_existing_deps(tmp_path)
    test_mobile_scaffold_capacitor_pins_latest_to_6x(tmp_path)
    test_mobile_scaffold_capacitor_migrates_storage_to_preferences(tmp_path)
    test_mobile_scaffold_capacitor_pins_ios_latest_to_6x(tmp_path)
    test_mobile_scaffold_capacitor_overrides_incompatible_platform_versions(tmp_path)
    test_mobile_scaffold_capacitor_updates_webdir_in_existing_config(tmp_path)
    test_mobile_scaffold_kivy(tmp_path)
    test_web_builder_scaffold_noop(tmp_path)
    test_web_builder_build_no_cmd(tmp_path)
    test_patch_no_sandbox_user_provided_main_js(tmp_path)
    test_patch_no_sandbox_already_patched(tmp_path)
    test_patch_no_sandbox_scaffolded_default(tmp_path)
    test_patch_no_sandbox_desktop_notes_main_js(tmp_path)
    test_patch_no_sandbox_no_main_js(tmp_path)
    test_patch_no_sandbox_double_quotes(tmp_path)
    test_patch_no_sandbox_es_module_single_quotes(tmp_path)
    test_patch_no_sandbox_es_module_double_quotes(tmp_path)
    test_patch_no_sandbox_ultimate_fallback(tmp_path)
    test_generate_linux_launcher_creates_files(tmp_path)
    test_generate_linux_launcher_no_dist(tmp_path)
    test_generate_linux_launcher_no_appimage(tmp_path)
    test_build_result_defaults()
    test_mobile_scaffold_capacitor_updates_plugin_versions(tmp_path)
    test_desktop_scaffold_tauri_window_dimensions(tmp_path)
    test_desktop_scaffold_tauri_default_dimensions(tmp_path)
    test_desktop_scaffold_tauri_does_not_overwrite_existing_config(tmp_path)
    test_desktop_scaffold_tauri_bundle_identifier(tmp_path)
    test_desktop_scaffold_pyqt(tmp_path)
    test_desktop_scaffold_pyqt_with_icon(tmp_path)
    test_desktop_scaffold_tkinter(tmp_path)
    test_desktop_scaffold_tkinter_does_not_overwrite_existing_spec(tmp_path)
    test_desktop_scaffold_flutter_desktop_noop(tmp_path)
    test_desktop_scaffold_unknown_framework_noop(tmp_path)
    test_electron_builder_flags_linux_only()
    test_electron_builder_flags_empty_defaults_to_linux()
    test_electron_builder_flags_none_defaults_to_linux()
    test_electron_builder_flags_windows_skipped_on_linux_no_wine(mock_which;mock_sys)
    test_electron_builder_flags_windows_allowed_with_wine(mock_which;mock_sys)
    test_electron_builder_flags_mac_skipped_on_linux(mock_which;mock_sys)
    test_electron_builder_flags_mac_allowed_on_darwin(mock_which;mock_sys)
    test_electron_builder_flags_windows_on_windows(mock_which;mock_sys)
    test_electron_builder_flags_deduplicates()
    test_electron_builder_flags_aliases()
    test_filter_electron_builder_cmd_strips_windows_on_linux(mock_which;mock_sys)
    test_filter_electron_builder_cmd_ensures_at_least_one_platform(mock_which;mock_sys)
    test_desktop_default_build_cmd_electron_linux()
    test_desktop_default_build_cmd_electron_multi_target(mock_which;mock_sys)
    test_desktop_default_build_cmd_tauri()
    test_desktop_default_build_cmd_pyinstaller()
    test_desktop_default_build_cmd_tkinter()
    test_desktop_default_build_cmd_pyqt()
    test_desktop_default_build_cmd_flutter_linux()
    test_desktop_default_build_cmd_flutter_windows()
    test_desktop_default_build_cmd_flutter_macos()
    test_desktop_default_build_cmd_unknown_framework()
    test_desktop_collect_artifacts_electron_appimage(tmp_path)
    test_desktop_collect_artifacts_electron_dmg(tmp_path)
    test_desktop_collect_artifacts_electron_snap(tmp_path)
    test_desktop_collect_artifacts_electron_run_sh(tmp_path)
    test_desktop_collect_artifacts_tauri(tmp_path)
    test_desktop_collect_artifacts_pyinstaller(tmp_path)
    test_desktop_collect_artifacts_pyqt(tmp_path)
    test_desktop_collect_artifacts_tkinter(tmp_path)
    test_desktop_collect_artifacts_flutter(tmp_path)
    test_desktop_collect_artifacts_empty(tmp_path)
    test_desktop_collect_artifacts_unknown_framework_fallback(tmp_path)
    test_desktop_scaffold_electron_build_targets(tmp_path)
    test_desktop_scaffold_electron_move_electron_to_dev_deps(tmp_path)
    test_desktop_scaffold_electron_ensure_dev_deps_added(tmp_path)
    test_desktop_build_no_cmd_returns_failure()
    test_mobile_scaffold_react_native(tmp_path)
    test_mobile_scaffold_react_native_default_display_name(tmp_path)
    test_mobile_scaffold_react_native_does_not_overwrite(tmp_path)
    test_mobile_scaffold_kivy_app_id(tmp_path)
    test_mobile_scaffold_kivy_no_fullscreen(tmp_path)
    test_mobile_scaffold_kivy_does_not_overwrite(tmp_path)
    test_mobile_scaffold_kivy_has_required_sections(tmp_path)
    test_mobile_scaffold_flutter_noop(tmp_path)
    test_mobile_scaffold_unknown_framework_noop(tmp_path)
    test_mobile_capacitor_webdir_priority_dist_over_www(tmp_path)
    test_mobile_capacitor_webdir_priority_build(tmp_path)
    test_mobile_capacitor_webdir_priority_public(tmp_path)
    test_mobile_capacitor_webdir_no_index_defaults_to_dist(tmp_path)
    test_mobile_default_build_cmd_capacitor_android()
    test_mobile_default_build_cmd_capacitor_ios()
    test_mobile_default_build_cmd_react_native_android()
    test_mobile_default_build_cmd_react_native_ios()
    test_mobile_default_build_cmd_flutter_android()
    test_mobile_default_build_cmd_flutter_ios()
    test_mobile_default_build_cmd_kivy_android()
    test_mobile_default_build_cmd_kivy_ios()
    test_mobile_default_build_cmd_unknown_framework()
    test_mobile_default_build_cmd_empty_targets_defaults_android()
    test_mobile_collect_artifacts_capacitor_apk(tmp_path)
    test_mobile_collect_artifacts_capacitor_ipa(tmp_path)
    test_mobile_collect_artifacts_capacitor_both(tmp_path)
    test_mobile_collect_artifacts_react_native_apk(tmp_path)
    test_mobile_collect_artifacts_react_native_ipa(tmp_path)
    test_mobile_collect_artifacts_flutter_apk(tmp_path)
    test_mobile_collect_artifacts_flutter_ipa(tmp_path)
    test_mobile_collect_artifacts_kivy_apk(tmp_path)
    test_mobile_collect_artifacts_kivy_aab(tmp_path)
    test_mobile_collect_artifacts_empty(tmp_path)
    test_mobile_collect_artifacts_unknown_framework_fallback(tmp_path)
    test_mobile_build_no_cmd_returns_failure()
    test_mobile_ensure_cap_platforms_skips_existing_dir(tmp_path)
    test_mobile_ensure_cap_platforms_runs_cap_add(tmp_path)
    test_mobile_ensure_cap_platforms_multiple_targets(tmp_path)
    test_mobile_ensure_cap_platforms_partial_existing(tmp_path)
    test_mobile_build_capacitor_calls_ensure_platforms(tmp_path)
    test_web_builder_platform_name()
    test_web_builder_scaffold_multiple_frameworks(tmp_path)
    test_web_builder_build_result_structure(tmp_path)
    test_build_result_all_fields()
    test_build_result_failure()
    test_target_config_from_dict_desktop_electron()
    test_target_config_from_dict_mobile_capacitor()
    test_target_config_from_dict_mobile_react_native()
    test_target_config_from_dict_mobile_flutter()
    test_target_config_from_dict_mobile_kivy()
    test_target_config_from_dict_desktop_tauri()
    test_target_config_from_dict_desktop_pyinstaller()
    test_target_config_from_dict_desktop_pyqt()
    test_target_config_from_dict_desktop_tkinter()
    test_target_config_from_dict_web_default()
    test_target_config_from_dict_unknown_platform_defaults_web()
    test_target_config_from_dict_targets_as_csv_string()
    test_target_config_from_dict_extra_keys_preserved()
    test_target_config_from_yaml_body()
    test_target_config_from_yaml_body_invalid()
    test_effective_build_targets_desktop_explicit()
    test_effective_build_targets_desktop_default()
    test_effective_build_targets_mobile_explicit()
    test_effective_build_targets_mobile_default()
    test_effective_build_targets_web_empty()
    test_target_config_framework_meta_electron()
    test_target_config_framework_meta_capacitor()
    test_target_config_framework_meta_pyinstaller()
    test_target_config_framework_meta_none()
    test_framework_registry_has_all_desktop_frameworks()
    test_framework_registry_has_all_mobile_frameworks()
    test_framework_registry_desktop_platforms()
    test_framework_registry_mobile_platforms()
    test_framework_registry_all_have_build_cmd()
    test_framework_registry_all_have_artifact_patterns()
    test_framework_registry_node_frameworks()
    test_framework_registry_python_frameworks()
    test_get_framework_meta_case_insensitive()
    test_get_framework_meta_unknown()
    test_list_frameworks_all()
    test_list_frameworks_desktop_only()
    test_list_frameworks_mobile_only()
    test_infer_target_electron()
    test_infer_target_tauri()
    test_infer_target_pyinstaller()
    test_infer_target_pyqt()
    test_infer_target_tkinter()
    test_infer_target_capacitor()
    test_infer_target_react_native()
    test_infer_target_expo()
    test_infer_target_buildozer()
    test_infer_target_flutter()
    test_infer_target_web_default()
    test_infer_target_empty_deps()
    test_infer_target_mobile_over_desktop_when_both_hinted()
    test_get_builder_for_target_mobile_capacitor()
    test_get_builder_for_target_mobile_react_native()
    test_get_builder_for_target_mobile_flutter()
    test_get_builder_for_target_mobile_kivy()
    test_get_builder_for_target_desktop_electron()
    test_get_builder_for_target_desktop_tauri()
    test_get_builder_for_target_desktop_pyinstaller()
    test_get_builder_for_target_desktop_pyqt()
    test_get_builder_for_target_desktop_tkinter()
    test_get_builder_for_target_web_fastapi()
  tests/test_config.py:
    e: test_dependency_config_from_string,test_dependency_config_from_dict,test_service_config_from_dict,test_ecosystem_config_from_dict,test_ecosystem_config_auto_port,test_ecosystem_config_from_yaml,test_ecosystem_config_to_dict,test_load_config_file_not_found,test_registry_config_defaults,test_cache_config_from_env_prefers_pactown_prefixed_vars,test_cache_config_to_env_sets_pip_extra_when_missing,test_cache_config_to_docker_build_args_maps_apt_proxy,test_cache_config_from_env_reads_pip_timeout_and_retries,test_cache_config_to_env_includes_timeout_and_retries,test_cache_config_to_docker_build_args_includes_timeout_and_retries
    test_dependency_config_from_string()
    test_dependency_config_from_dict()
    test_service_config_from_dict()
    test_ecosystem_config_from_dict()
    test_ecosystem_config_auto_port()
    test_ecosystem_config_from_yaml()
    test_ecosystem_config_to_dict()
    test_load_config_file_not_found()
    test_registry_config_defaults()
    test_cache_config_from_env_prefers_pactown_prefixed_vars(monkeypatch)
    test_cache_config_to_env_sets_pip_extra_when_missing()
    test_cache_config_to_docker_build_args_maps_apt_proxy()
    test_cache_config_from_env_reads_pip_timeout_and_retries(monkeypatch)
    test_cache_config_to_env_includes_timeout_and_retries()
    test_cache_config_to_docker_build_args_includes_timeout_and_retries()
  tests/test_cross_platform.py:
    e: _deploy_config,_create_artifacts,TestDesktopElectronAllOS,TestDesktopTauriAllOS,TestDesktopPyInstallerAllOS,TestDesktopPyQtAllOS,TestDesktopTkinterAllOS,TestDesktopFlutterAllOS,TestMobileCapacitorAllPlatforms,TestMobileReactNativeAllPlatforms,TestMobileFlutterAllPlatforms,TestMobileKivyAllPlatforms,TestWebAllFrameworks,TestAnsibleDeployDesktopAllCombinations,TestAnsibleDeployMobileAllCombinations,TestAnsibleDeployWebAllFrameworks,TestFrameworkRegistryCompleteness,TestBuildCommandMatrix,TestArtifactCollectionMatrix,TestElectronNoSandboxAllPatterns,TestElectronBuilderFlagFilteringAllOS,TestElectronParallelBuild,TestFullE2EAllDesktopCombinations,TestFullE2EAllMobileCombinations
    TestDesktopElectronAllOS: sandbox(1),test_scaffold_creates_package_json_and_main_js(1),test_scaffold_package_json_has_all_os_targets(1),test_scaffold_main_js_has_no_sandbox(1),test_scaffold_electron_dev_deps(1),test_scaffold_app_id(1),test_scaffold_custom_window_size(1),test_artifacts_per_os(2),test_build_cmd_per_os(1),test_build_cmd_multi_os(0),test_linux_artifacts_include_launcher(1),test_all_os_artifacts_combined(1)  # Electron × linux, windows, macos.
    TestDesktopTauriAllOS: sandbox(1),test_scaffold_creates_tauri_conf(1),test_scaffold_custom_app_id(1),test_scaffold_custom_window_size(1),test_artifacts_per_os(2),test_build_cmd(0),test_all_os_artifacts_combined(1)  # Tauri × linux, windows, macos.
    TestDesktopPyInstallerAllOS: sandbox(1),test_scaffold_creates_spec(1),test_scaffold_with_icon(1),test_artifacts_per_os(2),test_build_cmd_same_for_all_os(1),test_all_os_artifacts_combined(1)  # PyInstaller × linux, windows, macos.
    TestDesktopPyQtAllOS: sandbox(1),test_scaffold_creates_spec(1),test_artifacts_per_os(2),test_build_cmd_same_for_all_os(1)  # PyQt × linux, windows, macos.
    TestDesktopTkinterAllOS: sandbox(1),test_scaffold_creates_spec(1),test_artifacts_per_os(2),test_build_cmd_same_for_all_os(1)  # Tkinter × linux, windows, macos.
    TestDesktopFlutterAllOS: sandbox(1),test_scaffold_noop(1),test_artifacts_per_os(2),test_build_cmd_per_os(1)  # Flutter desktop × linux, windows, macos.
    TestMobileCapacitorAllPlatforms: sandbox(1),test_scaffold_creates_config(1),test_scaffold_config_content(1),test_scaffold_custom_app_id(1),test_scaffold_package_json_deps(1),test_scaffold_android_platform_dep(1),test_scaffold_ios_platform_dep(1),test_scaffold_dual_platform_deps(1),test_scaffold_scripts(1),test_scaffold_web_dir_detection_dist(1),test_scaffold_web_dir_detection_root(1),test_artifacts_per_platform(2),test_build_cmd_per_platform(1),test_dual_platform_artifacts(1)  # Capacitor × android, ios.
    TestMobileReactNativeAllPlatforms: sandbox(1),test_scaffold_creates_app_json(1),test_scaffold_app_json_content(1),test_scaffold_custom_display_name(1),test_artifacts_per_platform(2),test_build_cmd_android(0),test_build_cmd_ios(0),test_dual_platform_artifacts(1)  # React Native × android, ios.
    TestMobileFlutterAllPlatforms: sandbox(1),test_scaffold_noop(1),test_artifacts_per_platform(2),test_build_cmd_android(0),test_build_cmd_ios(0)  # Flutter mobile × android, ios.
    TestMobileKivyAllPlatforms: sandbox(1),test_scaffold_creates_buildozer_spec(1),test_scaffold_custom_app_id(1),test_scaffold_fullscreen(1),test_scaffold_no_fullscreen(1),test_scaffold_icon(1),test_artifacts_per_platform(2),test_build_cmd_android(0),test_build_cmd_ios(0),test_android_apk_and_aab(1)  # Kivy × android, ios.
    TestWebAllFrameworks: sandbox(1),test_scaffold_noop(2),test_build_no_cmd_returns_success(2),test_build_with_cmd_runs_shell(2),test_platform_name(0)  # WebBuilder × all web frameworks.
    TestAnsibleDeployDesktopAllCombinations: test_scaffold_artifacts_ansible_deploy(3)  # Ansible deploy for every desktop framework × OS combination.
    TestAnsibleDeployMobileAllCombinations: test_scaffold_artifacts_ansible_deploy(3)  # Ansible deploy for every mobile framework × platform combina
    TestAnsibleDeployWebAllFrameworks: test_web_framework_ansible_deploy(2)  # Ansible deploy for every web framework.
    TestFrameworkRegistryCompleteness: test_all_desktop_frameworks_registered(0),test_all_mobile_frameworks_registered(0),test_all_frameworks_have_build_cmd(0),test_all_frameworks_have_artifact_patterns(0),test_desktop_enums_match_registry(0),test_mobile_enums_match_registry(0),test_web_enums(0)  # Verify all frameworks are registered and have correct metada
    TestBuildCommandMatrix: test_electron_build_cmd_targets(1),test_tauri_build_cmd_ignores_targets(0),test_python_desktop_build_cmd(1),test_flutter_desktop_build_cmd(1),test_capacitor_build_cmd(1),test_react_native_build_cmd(1),test_flutter_mobile_build_cmd(1),test_kivy_build_cmd(1),test_unknown_desktop_framework_returns_empty(0),test_unknown_mobile_framework_returns_empty(0)  # Verify build commands for every framework × target combinati
    TestArtifactCollectionMatrix: test_desktop_artifact_collection(3),test_flutter_desktop_linux_artifacts(1),test_mobile_artifact_collection(3),test_flutter_mobile_android_artifacts(1),test_unknown_desktop_framework_fallback(1),test_unknown_mobile_framework_fallback(1),test_empty_sandbox_returns_no_artifacts(1)  # Verify artifact collection patterns for every framework × OS
    TestElectronNoSandboxAllPatterns: test_commonjs_require(1),test_commonjs_double_quotes(1),test_es_module_single_quotes(1),test_es_module_double_quotes(1),test_app_whenready_fallback(1),test_app_on_fallback(1),test_ultimate_fallback_prepend(1),test_skip_already_patched(1),test_no_main_js(1)  # Verify no-sandbox patch works for all code patterns.
    TestElectronBuilderFlagFilteringAllOS: test_linux_host_keeps_linux(2),test_linux_host_strips_mac(2),test_linux_host_strips_windows_no_wine(2),test_linux_host_keeps_windows_with_wine(2),test_linux_host_multi_target(2),test_macos_host_keeps_mac(2),test_macos_host_keeps_linux(2),test_windows_host_keeps_windows(2),test_windows_host_strips_mac(2),test_empty_targets_defaults_to_linux(0),test_none_targets_defaults_to_linux(0),test_no_duplicates(0),test_filter_cmd_strips_unsupported(0)  # Verify electron-builder flag filtering for all OS combinatio
    TestElectronParallelBuild: test_single_target_falls_back_to_sequential(1),test_non_electron_falls_back_to_sequential(1)  # Verify parallel build logic for Electron multi-target.
    TestFullE2EAllDesktopCombinations: test_all_os_e2e(2)  # End-to-end: scaffold → fake artifacts → collect → Ansible de
    TestFullE2EAllMobileCombinations: test_all_platforms_e2e(2)  # End-to-end: scaffold → fake artifacts → collect → Ansible de
    _deploy_config()
    _create_artifacts(sandbox;artifacts)
  tests/test_deploy_dockerfile.py:
    e: test_python_dockerfile_healthcheck_does_not_use_curl,test_python_dockerfile_supports_pip_timeout_and_retries_build_args,test_node_dockerfile_falls_back_when_package_lock_missing,test_markpact_readme_python_materializes_and_generates_cmd_from_run_block,test_markpact_readme_node_materializes_package_json_and_generates_cmd_from_run_block,test_markpact_readme_static_web_no_deps_generates_cmd_from_run_block
    test_python_dockerfile_healthcheck_does_not_use_curl()
    test_python_dockerfile_supports_pip_timeout_and_retries_build_args()
    test_node_dockerfile_falls_back_when_package_lock_missing()
    test_markpact_readme_python_materializes_and_generates_cmd_from_run_block()
    test_markpact_readme_node_materializes_package_json_and_generates_cmd_from_run_block()
    test_markpact_readme_static_web_no_deps_generates_cmd_from_run_block()
  tests/test_deploy_optimizations.py:
    e: TestNpmCiSelection,TestElectronLazyScaffold,TestParallelMultiTargetBuild,TestBuildLogStreaming,TestIncrementalBuilds,TestCacheDirectories,TestElectronPinnedVersions,TestRunShellContract
    TestNpmCiSelection: test_npm_install_when_no_lock(1),test_npm_ci_when_lock_exists(1),test_prefer_offline_only_without_lock(0)  # Verify _install_node_deps uses npm ci when package-lock.json
    TestElectronLazyScaffold: test_already_scaffolded_returns_true(1),test_not_scaffolded_no_main_js(1),test_not_scaffolded_missing_electron(1),test_not_scaffolded_no_package_json(1),test_not_scaffolded_invalid_json(1),test_scaffold_skips_when_already_done(1),test_scaffold_runs_when_not_done(1)
    TestParallelMultiTargetBuild: test_single_target_falls_back_to_sequential(1),test_non_electron_falls_back(1),test_explicit_build_cmd_falls_back(1),test_parallel_electron_multi_target(1),test_parallel_result_has_correct_fields(1)
    TestBuildLogStreaming: test_stderr_merged_into_stdout(1),test_on_log_receives_lines_in_order(1),test_build_error_visible_in_logs(1)
    TestIncrementalBuilds: _build(3),test_first_build_creates_hash_file(1),test_second_build_is_incremental(1),test_changed_readme_triggers_full_rebuild(1),test_incremental_still_scaffolds(1)
    TestCacheDirectories: test_all_cache_dirs_created(1),test_electron_builder_cache_created_on_build(1)
    TestElectronPinnedVersions: test_ensure_electron_dev_deps_uses_pinned(1),test_existing_version_not_overwritten(1)
    TestRunShellContract: test_success_returns_zero(1),test_failure_returns_nonzero(1),test_stderr_merged(1)
  tests/test_deploy_platforms.py:
    e: _readme,_sandbox_and_manager,_create_sandbox_from_readme,TestDeployDesktopElectron,TestDeployDesktopTauri,TestDeployDesktopPyInstaller,TestDeployDesktopPyQt,TestDeployDesktopTkinter,TestDeployDesktopFlutter,TestDeployMobileCapacitor,TestDeployMobileReactNative,TestDeployMobileKivy,TestDeployMobileFlutter,TestDeployWebFastAPI,TestDeployWebFlask,TestDeployWebExpress,TestDeployWebStatic,TestIaCSpecAllPlatforms,TestComposeHealthcheckPerPlatform,TestDockerfilePerPlatform,TestBuildServiceIntegration,TestNodeModulesCacheIntegration,TestFrameworkMetaDeploymentReady
    TestDeployDesktopElectron: test_sandbox_creation(1),test_target_parsing(0),test_scaffold_creates_package_json_and_main_js(1),test_build_produces_artifacts(1),test_build_result_has_logs(1),test_iac_spec_for_electron(1)
    TestDeployDesktopTauri: test_scaffold_creates_tauri_conf(1),test_full_build(1),test_default_build_cmd(0)
    TestDeployDesktopPyInstaller: test_scaffold_creates_spec(1),test_full_build(1),test_sandbox_writes_requirements(1),test_iac_python_runtime(1),test_dockerfile_generation(1)
    TestDeployDesktopPyQt: test_scaffold_creates_spec_with_icon(1),test_full_build(1),test_framework_meta(0)
    TestDeployDesktopTkinter: test_scaffold_and_build(1),test_default_cmd_uses_pyinstaller(0)
    TestDeployDesktopFlutter: test_parse_and_build(1),test_default_cmd(0)
    TestDeployMobileCapacitor: test_scaffold_creates_capacitor_config(1),test_scaffold_creates_package_json_scripts(1),test_full_build(1),test_builder_registry(0),test_iac_node_runtime(1)
    TestDeployMobileReactNative: test_scaffold_creates_app_json(1),test_full_build(1),test_default_cmd_android(0),test_default_cmd_ios(0)
    TestDeployMobileKivy: test_scaffold_creates_buildozer_spec(1),test_full_build(1),test_sandbox_creates_requirements(1),test_iac_python_runtime(1)
    TestDeployMobileFlutter: test_parse(0),test_build(1),test_default_cmd_android(0),test_default_cmd_ios(0)
    TestDeployWebFastAPI: test_sandbox_creation(1),test_iac_manifest(1),test_dockerfile_python_image(1),test_compose_yaml(1),test_web_builder_no_artifacts(1),test_run_cmd_extracted(0)
    TestDeployWebFlask: test_sandbox_creation(1),test_iac_manifest_python(1),test_dockerfile_python(1),test_compose_with_port(1)
    TestDeployWebExpress: test_sandbox_creates_package_json(1),test_iac_manifest_node(1),test_dockerfile_node_image(1),test_compose_healthcheck_node(1)
    TestDeployWebStatic: test_sandbox_no_deps(1),test_iac_manifest(1),test_web_builder_build_step(1)
    TestIaCSpecAllPlatforms: test_python_web_spec(0),test_node_web_spec(0),test_desktop_electron_spec(0),test_mobile_kivy_spec(0),test_mobile_capacitor_spec(0)  # Verify IaC sandbox spec is correct for every platform type.
    TestComposeHealthcheckPerPlatform: test_python_healthcheck_uses_urllib(0),test_node_healthcheck_uses_http_module(0),test_no_port_no_port_mapping(0)
    TestDockerfilePerPlatform: test_python_dockerfile(1),test_node_dockerfile(1),test_python_no_deps_no_requirements_copy(1),test_python_dockerfile_run_cmd_none(1),test_node_dockerfile_run_cmd_none(1)
    TestBuildServiceIntegration: _build(5),test_electron_build_service(1),test_pyinstaller_build_service(1),test_capacitor_build_service(1),test_kivy_build_service(1),test_web_build_service(1),test_build_failure_propagated(1),test_build_env_contains_electron_builder_cache(1)  # Tests that exercise SandboxManager.build_service() end-to-en
    TestNodeModulesCacheIntegration: test_node_cache_initialized(1),test_cache_dir_created(1),test_dep_cache_initialized(1)  # Verify that NodeModulesCache is wired into build_service.
    TestFrameworkMetaDeploymentReady: test_framework_has_build_cmd(1),test_framework_has_artifact_patterns(1),test_framework_platform_correct(2)  # Verify every registered framework has enough metadata for de
    _readme(content)
    _sandbox_and_manager(tmp)
    _create_sandbox_from_readme(tmp;readme_text;service_name;port;target;framework)
  tests/test_e2e_build.py:
    e: _write_readme,_parse_and_resolve,TestE2EDesktopElectron,TestE2EDesktopPyInstaller,TestE2EDesktopTauri,TestE2EMobileCapacitor,TestE2EMobileKivy,TestE2EWebBuilder,TestE2EServiceConfigTargets,TestE2ECrossPlatformScenario
    TestE2EDesktopElectron: test_parse_all_blocks(1),test_scaffold_creates_package_json(1),test_full_build_with_dummy_cmd(1),test_builder_registry_resolves_desktop(1)  # Full pipeline for an Electron desktop app.
    TestE2EDesktopPyInstaller: test_full_pipeline(1)
    TestE2EDesktopTauri: test_scaffold_and_parse(1)
    TestE2EMobileCapacitor: test_full_pipeline(1)
    TestE2EMobileKivy: test_full_pipeline(1)
    TestE2EWebBuilder: test_web_no_target_block_defaults_to_web(1),test_web_build_succeeds_without_cmd(1),test_web_build_with_optional_step(1)
    TestE2EServiceConfigTargets: test_service_config_from_dict_with_target(0),test_service_config_defaults_to_web(0),test_service_config_build_targets_as_csv_string(0)
    TestE2ECrossPlatformScenario: test_same_app_different_platforms(1),test_build_failure_returns_failed_result(1)  # Verify that the same builder infrastructure supports switchi
    _write_readme(tmp_path;content)
    _parse_and_resolve(readme)
  tests/test_e2e_build_extended.py:
    e: _write_readme,_parse_and_resolve,TestElectronDevDepsRegression,TestE2EDesktopPyQt,TestE2EDesktopTkinter,TestE2EDesktopTauriBuild,TestE2EMobileReactNative,TestE2EMobileFlutter,TestE2EDesktopFlutter,TestArtifactCollection,TestDefaultBuildCmdResolution,TestOnLogCallback,TestBuildWithEnvVars,TestScaffoldIdempotency,TestUnknownFrameworkFallback,TestTargetConfigEdgeCases,TestFrameworkRegistry,TestInferTargetFromDeps,TestExtractRunCommand,TestBuildFailures,TestServiceConfigBuildTargets,TestE2EPythonApiToElectronDesktop
    TestElectronDevDepsRegression: test_new_package_json_has_electron_in_dev_deps(1),test_existing_package_json_gets_electron_added(1),test_electron_moved_from_deps_to_dev_deps(1),test_ensure_electron_dev_deps_idempotent(1)  # Verify that _ensure_electron_dev_deps is called during scaff
    TestE2EDesktopPyQt: test_parse_pyqt_target(1),test_scaffold_creates_spec_with_icon(1),test_full_build(1),test_builder_registry_resolves(1)
    TestE2EDesktopTkinter: test_parse_and_scaffold(1),test_full_build(1)
    TestE2EDesktopTauriBuild: test_scaffold_with_window_size(1),test_full_build_with_artifact_collection(1)
    TestE2EMobileReactNative: test_parse_react_native(1),test_scaffold_creates_app_json(1),test_scaffold_react_native_custom_display_name(1),test_full_build(1),test_builder_registry_resolves_mobile(1)
    TestE2EMobileFlutter: test_parse_flutter_mobile(1),test_scaffold_flutter_is_noop(1),test_full_build(1)
    TestE2EDesktopFlutter: test_parse(1),test_full_build(1)
    TestArtifactCollection: test_electron_artifacts(1),test_pyinstaller_artifacts(1),test_capacitor_apk_artifacts(1),test_kivy_artifacts(1),test_react_native_artifacts(1),test_flutter_mobile_artifacts(1),test_no_artifacts_empty_dir(1),test_tauri_artifacts(1)  # Verify that _collect_artifacts finds files matching framewor
    TestDefaultBuildCmdResolution: test_desktop_electron_default_cmd(0),test_desktop_tauri_default_cmd(0),test_desktop_pyinstaller_default_cmd(0),test_desktop_pyqt_default_cmd(0),test_desktop_flutter_default_cmd(0),test_desktop_flutter_default_cmd_no_targets(0),test_mobile_capacitor_default_cmd(0),test_mobile_react_native_android_default_cmd(0),test_mobile_react_native_ios_default_cmd(0),test_mobile_flutter_android_default_cmd(0),test_mobile_flutter_ios_default_cmd(0),test_mobile_kivy_default_cmd(0),test_unknown_framework_returns_empty(0),test_no_cmd_no_framework_returns_failed_result(1),test_mobile_no_cmd_no_framework_returns_failed_result(1)  # When no markpact:build block is present, the builder should 
    TestOnLogCallback: test_desktop_build_streams_logs(1),test_mobile_build_streams_logs(1),test_web_build_streams_logs(1),test_scaffold_sends_log(1),test_broken_on_log_does_not_crash(1)  # Verify that on_log receives build progress messages.
    TestBuildWithEnvVars: test_env_passed_to_build_cmd(1),test_mobile_env_passed(1)
    TestScaffoldIdempotency: test_electron_scaffold_twice(1),test_tauri_scaffold_twice(1),test_capacitor_scaffold_twice(1),test_kivy_scaffold_twice(1),test_pyinstaller_scaffold_twice(1),test_react_native_scaffold_twice(1)  # Scaffolding the same directory twice should not break anythi
    TestUnknownFrameworkFallback: test_desktop_unknown_framework_scaffold_noop(1),test_mobile_unknown_framework_scaffold_noop(1),test_desktop_empty_framework_scaffold_noop(1),test_mobile_empty_framework_scaffold_noop(1)
    TestTargetConfigEdgeCases: test_from_dict_unknown_platform_defaults_to_web(0),test_targets_as_csv_string(0),test_effective_build_targets_defaults(0),test_effective_build_targets_explicit(0),test_is_buildable(0),test_needs_port(0),test_extra_fields_preserved(0),test_window_dimensions_parsed_as_int(0),test_window_dimensions_invalid_returns_none(0)
    TestFrameworkRegistry: test_all_desktop_frameworks_registered(0),test_all_mobile_frameworks_registered(0),test_flutter_desktop_registered(0),test_flutter_mobile_registered(0),test_case_insensitive_lookup(0),test_unknown_framework_returns_none(0),test_list_frameworks_all(0),test_list_frameworks_desktop(0),test_list_frameworks_mobile(0),test_node_frameworks_have_needs_node_true(0),test_python_frameworks_have_needs_python_true(0),test_every_framework_has_default_build_cmd(0)
    TestInferTargetFromDeps: test_electron_dep_infers_desktop(0),test_pyqt_dep_infers_desktop(0),test_capacitor_dep_infers_mobile(0),test_react_native_dep_infers_mobile(0),test_buildozer_dep_infers_mobile(0),test_fastapi_dep_infers_web(0),test_empty_deps_infers_web(0),test_mobile_takes_priority_over_desktop(0)
    TestExtractRunCommand: test_explicit_run_block(1),test_framework_default_run_cmd(1),test_file_heuristic_main_py(1),test_file_heuristic_index_js(1),test_no_run_cmd_returns_none(1)
    TestBuildFailures: test_desktop_build_failure_returns_details(1),test_mobile_build_failure_returns_details(1),test_web_build_failure_returns_details(1),test_build_with_stderr_captured(1)
    TestServiceConfigBuildTargets: test_desktop_electron_from_service_config(0),test_mobile_capacitor_from_service_config(0),test_mobile_kivy_from_service_config(0),test_desktop_pyqt_from_service_config(0)
    TestE2EPythonApiToElectronDesktop: test_parse_python_api_as_electron(1),test_scaffold_with_python_deps_package_json(1),test_full_build_succeeds(1)  # Regression test for the exact scenario that caused the origi
    _write_readme(tmp_path;content)
    _parse_and_resolve(readme)
  tests/test_e2e_deploy_desktop_mobile.py:
    e: _make_proc_mock,_fake_popen_factory,_write_readme,_headless_env,manager,_deploy,TestE2EDeployElectron,TestE2EDeployPyQt,TestE2EDeployTauri,TestE2EDeployCapacitor,TestE2EDeployKivy,TestE2EDeployReactNative,TestE2EWebServiceNotAffected,TestE2EAssetDiscovery,TestE2EPreviewCommandGeneration,TestE2EDetectionPerFramework,TestE2ESystemDeps
    TestE2EDeployElectron: test_headless_deploys_via_http(4),test_headless_serves_correct_port(4),test_scaffold_creates_electron_files(1),test_native_with_display(3),test_index_html_written_to_sandbox(4)
    TestE2EDeployPyQt: test_headless_deploys_via_http(4),test_scaffold_creates_spec(1),test_native_with_display(3)
    TestE2EDeployTauri: test_headless_deploys_via_http(4),test_scaffold_creates_tauri_config(1),test_native_with_display(3)
    TestE2EDeployCapacitor: test_headless_deploys_via_http(4),test_serves_from_www_dir(4),test_scaffold_creates_capacitor_config(1),test_native_with_display(3)
    TestE2EDeployKivy: test_headless_deploys_via_http(4),test_scaffold_creates_buildozer_spec(1),test_native_with_display(3)
    TestE2EDeployReactNative: test_headless_deploys_via_http(4),test_native_with_display(3)
    TestE2EWebServiceNotAffected: test_fastapi_runs_normally_on_headless(4),test_express_runs_normally_on_headless(4)
    TestE2EAssetDiscovery: test_capacitor_www_dir(1),test_react_build_dir(1),test_vite_dist_dir(1),test_public_dir(1),test_root_fallback(1),test_no_index_falls_back_to_root(1),test_priority_www_over_dist(1),test_priority_dist_over_build(1)
    TestE2EPreviewCommandGeneration: test_python_fallback_includes_bind(2),test_npx_serve_with_spa_flag(2),test_serves_subdir_when_index_in_www(2),test_venv_python_preferred(2),test_creates_fallback_html_for_python_desktop(2)
    TestE2EDetectionPerFramework: _no_display(1),test_electron_dot(0),test_npx_electron(0),test_cap_run(0),test_cap_open(0),test_tauri_dev(0),test_flutter_run(0),test_react_native_run(0),test_python_main_with_kivy_target(0),test_python_main_with_pyqt_target(0),test_python_main_with_pyinstaller_target(0),test_python_main_with_tkinter_target(0),test_python_main_without_target_not_affected(0),test_uvicorn_not_affected(0),test_node_not_affected(0),test_display_set_skips_preview(0),test_xvfb_available_skips_preview(1),test_target_cfg_framework_triggers_preview(0),test_web_target_not_affected(0)
    TestE2ESystemDeps: test_framework_system_deps_registry_has_tkinter(0),test_framework_system_deps_registry_has_electron(0),test_framework_system_deps_registry_has_kivy(0),test_import_to_apt_maps_tkinter(0),test_install_system_deps_skips_unknown_framework(1),test_install_system_deps_skips_when_all_installed(1),test_install_system_deps_calls_apt_when_missing(1),test_install_system_deps_nonfatal_on_apt_missing(1)
    _make_proc_mock()
    _fake_popen_factory(captured)
    _write_readme(tmp_path;content)
    _headless_env(monkeypatch)
    manager(tmp_path;monkeypatch)
    _deploy(manager;tmp_path;monkeypatch;readme_text;port)
  tests/test_electron_xvfb.py:
    e: _make_proc_mock,manager,readme_path,service,_fake_popen_factory,TestDetectWebPreviewNeeded,TestFindWebAssetsDir,TestBuildWebPreviewCmd,TestWebPreviewIntegration
    TestDetectWebPreviewNeeded: test_electron_cmd_no_display_no_xvfb(1),test_electron_cmd_with_display(1),test_electron_cmd_with_xvfb(1),test_capacitor_cmd_headless(1),test_web_cmd_not_affected(1),test_python_main_only_native_with_target(1),test_python_main_native_with_desktop_target(1)
    TestFindWebAssetsDir: test_index_at_root(1),test_www_subdir(1),test_dist_subdir(1),test_fallback_to_root(1),test_www_preferred_over_dist(1)
    TestBuildWebPreviewCmd: test_fallback_to_python_http_server(2),test_uses_npx_serve_when_available(2)
    TestWebPreviewIntegration: test_electron_uses_web_preview_on_headless(4),test_electron_runs_natively_with_display(4)
    _make_proc_mock()
    manager(tmp_path;monkeypatch)
    readme_path(tmp_path)
    service(readme_path)
    _fake_popen_factory(captured)
  tests/test_iac_manifest.py:
    e: test_create_sandbox_writes_iac_manifest_and_compose_and_dockerfile,test_create_sandbox_node_inferred_writes_manifest
    test_create_sandbox_writes_iac_manifest_and_compose_and_dockerfile()
    test_create_sandbox_node_inferred_writes_manifest()
  tests/test_llm.py:
    e: TestLLMStatus,TestLLMPriority,TestLLMReset,TestLLMTest,TestLLMDoctor,TestLLMModule,TestPactownLLMClass
    TestLLMStatus: test_llm_status_without_lolm(0),test_llm_status_with_providers(0),test_llm_status_no_providers_available(0)  # Tests for pactown llm status command.
    TestLLMPriority: test_llm_priority_set_success(0),test_llm_priority_set_failure(0),test_llm_priority_without_lolm(0)  # Tests for pactown llm priority command.
    TestLLMReset: test_llm_reset_success(0),test_llm_reset_failure(0)  # Tests for pactown llm reset command.
    TestLLMTest: test_llm_test_basic(0),test_llm_test_with_rotation(0),test_llm_test_with_provider(0),test_llm_test_error(0)  # Tests for pactown llm test command.
    TestLLMDoctor: test_llm_doctor_outputs_environment_info(0)  # Tests for pactown llm doctor command.
    TestLLMModule: test_is_lolm_available_false(0),test_get_llm_status_without_lolm(0)  # Tests for pactown.llm module functions.
    TestPactownLLMClass: test_pactown_llm_singleton(0),test_pactown_llm_generate_with_rotation(0)  # Tests for PactownLLM class.
  tests/test_markpact_blocks.py:
    e: test_parse_blocks_new_format_includes_lang,test_parse_blocks_old_format_is_supported,test_parse_blocks_run_block_new_format,test_extract_run_command_explicit_block,test_extract_run_command_from_target_framework,test_extract_run_command_file_heuristic_main_py,test_extract_run_command_file_heuristic_index_js,test_extract_run_command_returns_none_when_no_hint,test_extract_run_command_explicit_overrides_framework
    test_parse_blocks_new_format_includes_lang()
    test_parse_blocks_old_format_is_supported()
    test_parse_blocks_run_block_new_format()
    test_extract_run_command_explicit_block()
    test_extract_run_command_from_target_framework()
    test_extract_run_command_file_heuristic_main_py()
    test_extract_run_command_file_heuristic_index_js()
    test_extract_run_command_returns_none_when_no_hint()
    test_extract_run_command_explicit_overrides_framework()
  tests/test_markpact_target_blocks.py:
    e: test_parse_target_block_yaml,test_extract_target_config_desktop,test_extract_target_config_mobile,test_extract_target_config_none_when_missing,test_parse_build_block,test_extract_build_cmd,test_extract_build_cmd_none_when_missing,test_full_desktop_markpact,test_full_mobile_markpact,test_get_meta_value
    test_parse_target_block_yaml()
    test_extract_target_config_desktop()
    test_extract_target_config_mobile()
    test_extract_target_config_none_when_missing()
    test_parse_build_block()
    test_extract_build_cmd()
    test_extract_build_cmd_none_when_missing()
    test_full_desktop_markpact()
    test_full_mobile_markpact()
    test_get_meta_value()
  tests/test_network.py:
    e: test_port_allocator_allocate,test_port_allocator_preferred_port,test_port_allocator_release,test_service_endpoint,test_service_registry_register,test_service_registry_get,test_service_registry_get_url,test_service_registry_environment,test_service_registry_unregister,test_service_registry_dynamic_port,test_find_free_port,test_check_port
    test_port_allocator_allocate()
    test_port_allocator_preferred_port()
    test_port_allocator_release()
    test_service_endpoint()
    test_service_registry_register()
    test_service_registry_get()
    test_service_registry_get_url()
    test_service_registry_environment()
    test_service_registry_unregister()
    test_service_registry_dynamic_port()
    test_find_free_port()
    test_check_port()
  tests/test_node_cache.py:
    e: _make_pkg_json,_populate_node_modules,TestHashStability,TestSaveRestore,TestPersistence,TestInvalidation,TestEviction,TestStats,TestOnLog,TestSortedDeps
    TestHashStability: test_same_deps_same_hash(0),test_different_deps_different_hash(0),test_order_independent(0),test_description_change_does_not_bust_cache(0),test_scripts_change_does_not_bust_cache(0),test_name_change_busts_cache(0),test_invalid_json_returns_stable_hash(0)
    TestSaveRestore: test_save_and_restore(1),test_cache_miss_returns_false(1),test_save_without_node_modules_returns_none(1),test_restore_overwrites_existing_node_modules(1)
    TestPersistence: test_new_instance_loads_existing_cache(1)
    TestInvalidation: test_invalidate_removes_entry(1),test_invalidate_nonexistent_is_noop(1)
    TestEviction: test_max_entries_evicts_lru(1)
    TestStats: test_get_stats_empty(1),test_get_stats_with_entries(1)
    TestOnLog: test_save_sends_log(1),test_restore_sends_log(1)
    TestSortedDeps: test_sorts_dict(0),test_non_dict_returns_empty(0),test_empty_dict(0)
    _make_pkg_json(name;deps;dev_deps)
    _populate_node_modules(sandbox;modules)
  tests/test_parallel.py:
    e: test_run_parallel_basic,test_run_parallel_with_error,test_run_parallel_timing,test_run_in_dependency_waves,test_run_in_dependency_waves_diamond,test_task_result_dataclass
    test_run_parallel_basic()
    test_run_parallel_with_error()
    test_run_parallel_timing()
    test_run_in_dependency_waves()
    test_run_in_dependency_waves_diamond()
    test_task_result_dataclass()
  tests/test_platform.py:
    e: test_normalize_host_strips_scheme_and_port,test_normalize_domain_strips_www_and_scheme,test_build_project_host_dash_separator_normalizes_username,test_build_project_host_dot_separator_normalizes_username,test_parse_project_host,test_build_project_subdomain_limits_length,test_build_service_subdomain_dash,test_build_service_subdomain_dot
    test_normalize_host_strips_scheme_and_port()
    test_normalize_domain_strips_www_and_scheme()
    test_build_project_host_dash_separator_normalizes_username()
    test_build_project_host_dot_separator_normalizes_username()
    test_parse_project_host(host)
    test_build_project_subdomain_limits_length()
    test_build_service_subdomain_dash()
    test_build_service_subdomain_dot()
  tests/test_quadlet_security.py:
    e: temp_dir,mock_systemctl,TestContainerNameInjection,TestEnvironmentVariableInjection,TestVolumeMountInjection,TestTraefikLabelInjection,TestSystemdUnitInjection,TestTenantIsolation,TestCommandInjection,TestAPISecurityInjection,TestSecurityHardening,TestInputSanitization
    TestContainerNameInjection: test_container_name_sanitization(0),test_filename_sanitization(0)  # Test container name sanitization against injection attacks.
    TestEnvironmentVariableInjection: test_env_value_sanitization(0),test_env_key_sanitization(0)  # Test environment variable injection attacks.
    TestVolumeMountInjection: test_volume_path_validation(0),test_volume_options_injection(0)  # Test volume mount path traversal and injection.
    TestTraefikLabelInjection: test_domain_injection(0),test_middleware_injection(0)  # Test Traefik routing label injection attacks.
    TestSystemdUnitInjection: test_section_injection(0),test_directive_injection(0)  # Test systemd unit file injection attacks.
    TestTenantIsolation: test_tenant_path_traversal(0),test_tenant_network_isolation(0)  # Test tenant isolation and privilege escalation.
    TestCommandInjection: test_health_check_injection(0),test_image_name_injection(0)  # Test command injection via various vectors.
    TestAPISecurityInjection: api_client(0),test_markdown_content_injection(1),test_tenant_id_injection(1)  # Test API endpoint security against injection.
    TestSecurityHardening: test_no_new_privileges(0),test_capability_drop(0),test_resource_limits(0),test_read_only_filesystem(0)  # Test that security hardening options are properly applied.
    TestInputSanitization: test_sanitize_name(0)  # Test input sanitization functions.
    temp_dir()
    mock_systemctl()
  tests/test_registry.py:
    e: test_artifact_version_to_dict,test_artifact_version_from_dict,test_artifact_full_name,test_artifact_add_version,test_artifact_get_version,test_registry_storage_save_and_get,test_registry_storage_list,test_registry_storage_delete,test_registry_storage_search,test_registry_storage_persistence
    test_artifact_version_to_dict()
    test_artifact_version_from_dict()
    test_artifact_full_name()
    test_artifact_add_version()
    test_artifact_get_version()
    test_registry_storage_save_and_get()
    test_registry_storage_list()
    test_registry_storage_delete()
    test_registry_storage_search()
    test_registry_storage_persistence()
  tests/test_resolver.py:
    e: make_config,test_startup_order_no_deps,test_startup_order_linear,test_startup_order_diamond,test_circular_dependency_detection,test_shutdown_order,test_resolve_service_deps,test_get_environment,test_validate_missing_dep,test_print_graph
    make_config(services)
    test_startup_order_no_deps()
    test_startup_order_linear()
    test_startup_order_diamond()
    test_circular_dependency_detection()
    test_shutdown_order()
    test_resolve_service_deps()
    test_get_environment()
    test_validate_missing_dep()
    test_print_graph()
  tests/test_runner_api.py:
    e: _sample_markdown,test_validate_ok,test_run_fails_fast_on_missing_required_env_vars,test_run_passes_pip_timeout_and_retries_to_pip_install,test_sandbox_prepare_and_file_ops,test_status_filtering,test_run_failure_includes_error_report_md,test_run_stream_failure_includes_error_report_md
    _sample_markdown()
    test_validate_ok(tmp_path)
    test_run_fails_fast_on_missing_required_env_vars(tmp_path)
    test_run_passes_pip_timeout_and_retries_to_pip_install(tmp_path;monkeypatch)
    test_sandbox_prepare_and_file_ops(tmp_path)
    test_status_filtering(tmp_path)
    test_run_failure_includes_error_report_md(tmp_path;monkeypatch)
    test_run_stream_failure_includes_error_report_md(tmp_path;monkeypatch)
  tests/test_sandbox_manager_env_injection.py:
    e: test_sandbox_manager_passes_env_to_pip_install
    test_sandbox_manager_passes_env_to_pip_install(tmp_path;monkeypatch)
  tests/test_sandbox_manager_node_deps.py:
    e: test_node_project_uses_npm_instead_of_pip_even_if_deps_lang_is_wrong,test_node_deps_block_creates_package_json_and_calls_npm
    test_node_project_uses_npm_instead_of_pip_even_if_deps_lang_is_wrong(tmp_path;monkeypatch)
    test_node_deps_block_creates_package_json_and_calls_npm(tmp_path;monkeypatch)
  tests/test_sandbox_manager_node_run_env.py:
    e: test_sandbox_manager_passes_env_to_node_run
    test_sandbox_manager_passes_env_to_node_run(tmp_path;monkeypatch)
  tests/test_sandbox_manager_venv_heal.py:
    e: test_self_heal_corrupted_cache
    test_self_heal_corrupted_cache(tmp_path)
  tests/test_security.py:
    e: _pip_audit_available,TestInputSanitization,TestPathTraversal,TestCommandInjection,TestSecretsLeakage,TestNetworkSecurity,TestAuthorizationChecks,TestRateLimiting,TestCryptography,TestDependencySecurity
    TestInputSanitization: test_service_name_rejects_path_traversal(0),test_tenant_id_sanitization(0)  # Test input sanitization functions.
    TestPathTraversal: test_sandbox_path_stays_within_root(0)  # Test path traversal prevention.
    TestCommandInjection: test_quadlet_sanitize_name(0),test_env_value_no_newlines(0)  # Test command injection prevention.
    TestSecretsLeakage: test_config_env_handling(0),test_error_messages_do_not_leak_secrets(0)  # Test that secrets are not leaked.
    TestNetworkSecurity: test_port_allocation_within_range(0),test_service_endpoint_creation(0)  # Test network-related security.
    TestAuthorizationChecks: test_security_policy_user_profile(0),test_service_runner_creates_sandbox(0)  # Test authorization and access control.
    TestRateLimiting: test_rate_limiter_exists(0),test_api_rate_limit_headers(0)  # Test rate limiting mechanisms.
    TestCryptography: test_no_weak_random(0)  # Test cryptographic practices.
    TestDependencySecurity: test_no_known_vulnerabilities(0)  # Test for known vulnerable dependencies.
    _pip_audit_available()
  tests/test_service_runner_fast_run_fallback.py:
    e: test_fast_run_fallback_sets_serviceconfig_readme_and_cleans_temp_file
    test_fast_run_fallback_sets_serviceconfig_readme_and_cleans_temp_file(tmp_path;monkeypatch)
  tests/test_service_runner_validation.py:
    e: test_validate_content_dependency_mismatch
    test_validate_content_dependency_mismatch()
  tests/test_targets.py:
    e: test_target_platform_values,test_target_config_from_yaml_desktop,test_target_config_from_yaml_mobile,test_target_config_defaults_to_web,test_target_config_from_dict_targets_as_string,test_target_config_effective_build_targets_desktop,test_target_config_effective_build_targets_mobile,test_target_config_effective_build_targets_explicit,test_target_config_extra_keys_preserved,test_get_framework_meta_electron,test_get_framework_meta_capacitor,test_get_framework_meta_pyinstaller,test_get_framework_meta_unknown,test_list_frameworks_all,test_list_frameworks_desktop_only,test_list_frameworks_mobile_only,test_infer_desktop_from_electron_dep,test_infer_mobile_from_capacitor_dep,test_infer_web_from_fastapi_dep,test_infer_web_from_empty_deps,test_infer_mobile_over_desktop_when_both
    test_target_platform_values()
    test_target_config_from_yaml_desktop()
    test_target_config_from_yaml_mobile()
    test_target_config_defaults_to_web()
    test_target_config_from_dict_targets_as_string()
    test_target_config_effective_build_targets_desktop()
    test_target_config_effective_build_targets_mobile()
    test_target_config_effective_build_targets_explicit()
    test_target_config_extra_keys_preserved()
    test_get_framework_meta_electron()
    test_get_framework_meta_capacitor()
    test_get_framework_meta_pyinstaller()
    test_get_framework_meta_unknown()
    test_list_frameworks_all()
    test_list_frameworks_desktop_only()
    test_list_frameworks_mobile_only()
    test_infer_desktop_from_electron_dep()
    test_infer_mobile_from_capacitor_dep()
    test_infer_web_from_fastapi_dep()
    test_infer_web_from_empty_deps()
    test_infer_mobile_over_desktop_when_both()
  tests/test_user_isolation_manager.py:
    e: test_sanitize_gecos_removes_colon_and_control_chars,test_get_or_create_user_non_root_virtual_user,test_get_or_create_user_reuses_existing_linux_user,test_get_or_create_user_root_creates_user_with_sanitized_comment,test_delete_user_root_builds_userdel_cmd
    test_sanitize_gecos_removes_colon_and_control_chars()
    test_get_or_create_user_non_root_virtual_user(tmp_path;monkeypatch)
    test_get_or_create_user_reuses_existing_linux_user(tmp_path;monkeypatch)
    test_get_or_create_user_root_creates_user_with_sanitized_comment(tmp_path;monkeypatch)
    test_delete_user_root_builds_userdel_cmd(tmp_path;monkeypatch)
  tools/sync_pactown_com_dependency.py:
    e: _read_pactown_version,_update_requirements_pin,main
    _read_pactown_version(pyproject_path)
    _update_requirements_pin(req_path)
    main()
  tools/validate_artifacts_docker.py:
    e: docker_available,docker_run,_py_script,_py_yaml_script,_reg,collect_artifacts,get_validator,_find_service_dir,validate_artifact,main,ValidationResult,ValidationReport
    ValidationResult:
    ValidationReport: total(0),passed(0),failed(0),print_summary(0)
    docker_available()
    docker_run(image;mount_src;mount_dst;script;timeout;retries)
    _py_script(code)
    _py_yaml_script(code)
    _reg(ext;image;script)
    collect_artifacts(root)
    get_validator(filepath)
    _find_service_dir(filepath;root)
    validate_artifact(filepath;root;docker_image;script_template)
    main()
```

### `project/logic.pl`

```prolog markpact:analysis path=project/logic.pl
% ── Project Metadata ─────────────────────────────────────
project_metadata('pactown', '0.1.170', 'python').

% ── Project Files ────────────────────────────────────────
project_file('app.doql.less', 434, 'less').
project_file('examples/fast-start-demo/demo.py', 121, 'python').
project_file('examples/security-policy/demo.py', 106, 'python').
project_file('examples/user-isolation/demo.py', 111, 'python').
project_file('project.sh', 59, 'shell').
project_file('src/pactown/__init__.py', 241, 'python').
project_file('src/pactown/builders/__init__.py', 19, 'python').
project_file('src/pactown/builders/base.py', 156, 'python').
project_file('src/pactown/builders/desktop.py', 666, 'python').
project_file('src/pactown/builders/mobile.py', 472, 'python').
project_file('src/pactown/builders/registry.py', 33, 'python').
project_file('src/pactown/builders/web.py', 94, 'python').
project_file('src/pactown/cli.py', 991, 'python').
project_file('src/pactown/config.py', 253, 'python').
project_file('src/pactown/deploy/__init__.py', 35, 'python').
project_file('src/pactown/deploy/ansible.py', 587, 'python').
project_file('src/pactown/deploy/base.py', 313, 'python').
project_file('src/pactown/deploy/compose.py', 440, 'python').
project_file('src/pactown/deploy/docker.py', 322, 'python').
project_file('src/pactown/deploy/kubernetes.py', 474, 'python').
project_file('src/pactown/deploy/podman.py', 422, 'python').
project_file('src/pactown/deploy/quadlet.py', 1045, 'python').
project_file('src/pactown/deploy/quadlet_api.py', 540, 'python').
project_file('src/pactown/deploy/quadlet_shell.py', 565, 'python').
project_file('src/pactown/error_context.py', 382, 'python').
project_file('src/pactown/events.py', 1076, 'python').
project_file('src/pactown/fast_start.py', 755, 'python').
project_file('src/pactown/generator.py', 214, 'python').
project_file('src/pactown/iac.py', 259, 'python').
project_file('src/pactown/llm.py', 454, 'python').
project_file('src/pactown/markpact_blocks.py', 70, 'python').
project_file('src/pactown/network.py', 271, 'python').
project_file('src/pactown/nfo_config.py', 211, 'python').
project_file('src/pactown/node_cache.py', 259, 'python').
project_file('src/pactown/orchestrator.py', 456, 'python').
project_file('src/pactown/parallel.py', 272, 'python').
project_file('src/pactown/platform.py', 147, 'python').
project_file('src/pactown/registry/__init__.py', 13, 'python').
project_file('src/pactown/registry/client.py', 261, 'python').
project_file('src/pactown/registry/models.py', 158, 'python').
project_file('src/pactown/registry/server.py', 218, 'python').
project_file('src/pactown/resolver.py', 163, 'python').
project_file('src/pactown/runner_api.py', 636, 'python').
project_file('src/pactown/runner_types.py', 255, 'python').
project_file('src/pactown/sandbox_helpers.py', 235, 'python').
project_file('src/pactown/sandbox_manager.py', 1840, 'python').
project_file('src/pactown/security.py', 691, 'python').
project_file('src/pactown/service_runner.py', 1235, 'python').
project_file('src/pactown/targets.py', 352, 'python').
project_file('src/pactown/user_isolation.py', 464, 'python').
project_file('tests/__init__.py', 2, 'python').
project_file('tests/conftest.py', 46, 'python').
project_file('tests/test_ansible.py', 7021, 'python').
project_file('tests/test_builders.py', 2045, 'python').
project_file('tests/test_config.py', 189, 'python').
project_file('tests/test_cross_platform.py', 1391, 'python').
project_file('tests/test_deploy_dockerfile.py', 190, 'python').
project_file('tests/test_deploy_optimizations.py', 413, 'python').
project_file('tests/test_deploy_platforms.py', 1310, 'python').
project_file('tests/test_e2e_build.py', 585, 'python').
project_file('tests/test_e2e_build_extended.py', 1397, 'python').
project_file('tests/test_e2e_deploy_desktop_mobile.py', 864, 'python').
project_file('tests/test_electron_xvfb.py', 246, 'python').
project_file('tests/test_iac_manifest.py', 85, 'python').
project_file('tests/test_llm.py', 312, 'python').
project_file('tests/test_markpact_blocks.py', 108, 'python').
project_file('tests/test_markpact_target_blocks.py', 242, 'python').
project_file('tests/test_network.py', 162, 'python').
project_file('tests/test_node_cache.py', 315, 'python').
project_file('tests/test_parallel.py', 150, 'python').
project_file('tests/test_platform.py', 57, 'python').
project_file('tests/test_quadlet_security.py', 691, 'python').
project_file('tests/test_registry.py', 154, 'python').
project_file('tests/test_resolver.py', 143, 'python').
project_file('tests/test_runner_api.py', 444, 'python').
project_file('tests/test_sandbox_manager_env_injection.py', 62, 'python').
project_file('tests/test_sandbox_manager_node_deps.py', 118, 'python').
project_file('tests/test_sandbox_manager_node_run_env.py', 95, 'python').
project_file('tests/test_sandbox_manager_venv_heal.py', 181, 'python').
project_file('tests/test_security.py', 293, 'python').
project_file('tests/test_service_runner_fast_run_fallback.py', 84, 'python').
project_file('tests/test_service_runner_validation.py', 78, 'python').
project_file('tests/test_targets.py', 170, 'python').
project_file('tests/test_user_isolation_manager.py', 153, 'python').
project_file('tools/sync_pactown_com_dependency.py', 90, 'python').
project_file('tools/validate_artifacts_docker.py', 547, 'python').
project_file('tree.sh', 2, 'shell').

% ── Python Functions ─────────────────────────────────────
python_function('examples/fast-start-demo/demo.py', 'main', 0, 4, 7).
python_function('examples/security-policy/demo.py', 'main', 0, 7, 12).
python_function('examples/user-isolation/demo.py', 'main', 0, 5, 17).
python_function('src/pactown/builders/mobile.py', '_sanitize_java_package_id', 1, 5, 6).
python_function('src/pactown/builders/registry.py', 'get_builder', 1, 2, 2).
python_function('src/pactown/builders/registry.py', 'get_builder_for_target', 1, 2, 1).
python_function('src/pactown/cli.py', 'is_lolm_available', 0, 1, 1).
python_function('src/pactown/cli.py', 'get_llm_status', 0, 1, 1).
python_function('src/pactown/cli.py', 'get_llm', 0, 1, 1).
python_function('src/pactown/cli.py', 'set_llm_priority', 2, 1, 2).
python_function('src/pactown/cli.py', 'reset_llm_provider', 1, 1, 2).
python_function('src/pactown/cli.py', 'cli', 0, 1, 2).
python_function('src/pactown/cli.py', 'up', 6, 9, 16).
python_function('src/pactown/cli.py', 'down', 1, 2, 8).
python_function('src/pactown/cli.py', 'status', 1, 2, 8).
python_function('src/pactown/cli.py', 'validate', 1, 3, 8).
python_function('src/pactown/cli.py', 'graph', 1, 2, 9).
python_function('src/pactown/cli.py', 'init', 2, 1, 6).
python_function('src/pactown/cli.py', 'publish', 2, 6, 13).
python_function('src/pactown/cli.py', 'pull', 2, 7, 11).
python_function('src/pactown/cli.py', 'scan', 1, 1, 4).
python_function('src/pactown/cli.py', 'generate', 4, 2, 9).
python_function('src/pactown/cli.py', 'build', 4, 14, 24).
python_function('src/pactown/cli.py', 'targets', 1, 5, 10).
python_function('src/pactown/cli.py', 'deploy', 4, 7, 16).
python_function('src/pactown/cli.py', 'quadlet', 0, 1, 1).
python_function('src/pactown/cli.py', 'quadlet_shell', 3, 1, 3).
python_function('src/pactown/cli.py', 'quadlet_api', 4, 1, 4).
python_function('src/pactown/cli.py', 'quadlet_generate', 6, 2, 10).
python_function('src/pactown/cli.py', 'quadlet_init', 3, 4, 8).
python_function('src/pactown/cli.py', 'quadlet_deploy', 6, 5, 15).
python_function('src/pactown/cli.py', 'quadlet_list', 1, 4, 11).
python_function('src/pactown/cli.py', 'quadlet_logs', 3, 2, 8).
python_function('src/pactown/cli.py', 'llm', 0, 1, 1).
python_function('src/pactown/cli.py', 'llm_status', 0, 18, 6).
python_function('src/pactown/cli.py', 'llm_doctor', 0, 12, 9).
python_function('src/pactown/cli.py', 'llm_priority', 2, 3, 5).
python_function('src/pactown/cli.py', 'llm_reset', 1, 3, 5).
python_function('src/pactown/cli.py', 'llm_test', 2, 5, 7).
python_function('src/pactown/cli.py', 'main', 1, 1, 1).
python_function('src/pactown/config.py', 'load_config', 1, 2, 4).
python_function('src/pactown/deploy/ansible.py', 'generate_inventory', 0, 5, 0).
python_function('src/pactown/deploy/ansible.py', 'generate_deploy_playbook', 0, 10, 1).
python_function('src/pactown/deploy/ansible.py', 'generate_teardown_playbook', 0, 1, 0).
python_function('src/pactown/deploy/ansible.py', 'generate_build_playbook', 0, 2, 0).
python_function('src/pactown/deploy/compose.py', 'generate_compose_from_config', 3, 4, 21).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_name', 1, 5, 4).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_env_value', 1, 2, 2).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_env_key', 1, 4, 3).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_path', 1, 3, 1).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_domain', 1, 3, 2).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_image', 1, 3, 2).
python_function('src/pactown/deploy/quadlet.py', 'sanitize_health_check', 1, 4, 3).
python_function('src/pactown/deploy/quadlet.py', 'validate_volume', 1, 7, 2).
python_function('src/pactown/deploy/quadlet.py', 'check_dangerous_content', 1, 3, 2).
python_function('src/pactown/deploy/quadlet.py', 'generate_traefik_quadlet', 1, 1, 2).
python_function('src/pactown/deploy/quadlet.py', 'generate_markdown_service_quadlet', 3, 3, 3).
python_function('src/pactown/deploy/quadlet_api.py', 'create_quadlet_api', 3, 1, 40).
python_function('src/pactown/deploy/quadlet_api.py', 'run_api', 4, 1, 2).
python_function('src/pactown/deploy/quadlet_shell.py', 'run_shell', 3, 2, 3).
python_function('src/pactown/error_context.py', '_truncate_text', 1, 4, 1).
python_function('src/pactown/error_context.py', 'extract_trace_ids', 1, 6, 6).
python_function('src/pactown/error_context.py', 'extract_file_paths', 1, 9, 4).
python_function('src/pactown/error_context.py', 'most_probable_file', 1, 7, 7).
python_function('src/pactown/error_context.py', '_is_noise_path', 1, 3, 3).
python_function('src/pactown/error_context.py', '_safe_resolve_under', 2, 4, 4).
python_function('src/pactown/error_context.py', '_read_text_limited', 1, 5, 3).
python_function('src/pactown/error_context.py', 'build_error_context', 0, 41, 26).
python_function('src/pactown/error_context.py', 'render_error_report_md', 1, 43, 15).
python_function('src/pactown/events.py', 'get_event_store', 1, 2, 1).
python_function('src/pactown/events.py', 'set_event_store', 1, 1, 0).
python_function('src/pactown/events.py', 'get_service_commands', 1, 2, 2).
python_function('src/pactown/events.py', 'get_service_queries', 1, 2, 2).
python_function('src/pactown/events.py', 'get_project_commands', 1, 2, 2).
python_function('src/pactown/events.py', 'get_project_queries', 1, 2, 2).
python_function('src/pactown/events.py', 'get_security_commands', 1, 2, 2).
python_function('src/pactown/events.py', 'get_security_queries', 1, 2, 2).
python_function('src/pactown/fast_start.py', '_heartbeat', 0, 3, 4).
python_function('src/pactown/fast_start.py', '_beat_every_s', 0, 2, 4).
python_function('src/pactown/fast_start.py', '_run_streamed', 1, 10, 7).
python_function('src/pactown/fast_start.py', 'get_fast_starter', 1, 3, 4).
python_function('src/pactown/generator.py', 'scan_readme', 1, 12, 8).
python_function('src/pactown/generator.py', 'scan_folder', 3, 5, 7).
python_function('src/pactown/generator.py', 'generate_config', 4, 9, 9).
python_function('src/pactown/generator.py', 'print_scan_results', 1, 5, 8).
python_function('src/pactown/iac.py', '_runtime_type', 0, 2, 0).
python_function('src/pactown/iac.py', '_default_base_image', 0, 2, 0).
python_function('src/pactown/iac.py', 'build_sandbox_spec', 0, 17, 9).
python_function('src/pactown/iac.py', 'write_sandbox_manifest', 0, 1, 2).
python_function('src/pactown/iac.py', 'build_single_service_compose', 0, 8, 3).
python_function('src/pactown/iac.py', 'write_single_service_compose', 0, 1, 2).
python_function('src/pactown/iac.py', 'write_sandbox_iac', 0, 5, 9).
python_function('src/pactown/llm.py', 'get_llm', 1, 1, 1).
python_function('src/pactown/llm.py', 'is_lolm_available', 0, 1, 0).
python_function('src/pactown/llm.py', 'get_lolm_info', 0, 1, 0).
python_function('src/pactown/llm.py', 'generate', 4, 3, 3).
python_function('src/pactown/llm.py', 'get_llm_status', 0, 3, 4).
python_function('src/pactown/llm.py', 'set_provider_priority', 2, 2, 4).
python_function('src/pactown/llm.py', 'reset_provider', 1, 2, 4).
python_function('src/pactown/markpact_blocks.py', 'extract_target_config', 1, 3, 1).
python_function('src/pactown/markpact_blocks.py', 'extract_build_cmd', 1, 4, 1).
python_function('src/pactown/markpact_blocks.py', 'extract_run_command', 1, 17, 4).
python_function('src/pactown/network.py', 'find_free_port', 2, 2, 2).
python_function('src/pactown/network.py', 'check_port', 1, 2, 3).
python_function('src/pactown/nfo_config.py', 'get_logger', 1, 3, 3).
python_function('src/pactown/nfo_config.py', 'setup_logging', 0, 11, 8).
python_function('src/pactown/node_cache.py', '_sorted_deps', 1, 2, 4).
python_function('src/pactown/node_cache.py', '_copytree_hardlink', 2, 3, 3).
python_function('src/pactown/orchestrator.py', 'run_ecosystem', 2, 5, 7).
python_function('src/pactown/parallel.py', 'run_parallel', 4, 8, 16).
python_function('src/pactown/parallel.py', 'run_in_dependency_waves', 4, 12, 13).
python_function('src/pactown/parallel.py', 'run_parallel_async', 2, 3, 9).
python_function('src/pactown/parallel.py', 'format_parallel_results', 1, 8, 5).
python_function('src/pactown/platform.py', 'coerce_subdomain_separator', 1, 2, 0).
python_function('src/pactown/platform.py', 'normalize_host', 1, 4, 5).
python_function('src/pactown/platform.py', 'normalize_domain', 1, 2, 3).
python_function('src/pactown/platform.py', 'is_local_domain', 1, 1, 1).
python_function('src/pactown/platform.py', 'build_origin', 0, 2, 2).
python_function('src/pactown/platform.py', 'web_base_url', 2, 2, 4).
python_function('src/pactown/platform.py', 'api_base_url', 2, 2, 4).
python_function('src/pactown/platform.py', 'to_dns_label', 1, 3, 3).
python_function('src/pactown/platform.py', 'parse_project_subdomain', 1, 5, 6).
python_function('src/pactown/platform.py', 'build_project_subdomain', 2, 1, 5).
python_function('src/pactown/platform.py', 'build_project_host', 2, 1, 2).
python_function('src/pactown/platform.py', 'parse_project_host', 1, 4, 5).
python_function('src/pactown/platform.py', 'build_service_subdomain', 2, 2, 3).
python_function('src/pactown/registry/server.py', 'create_app', 1, 1, 27).
python_function('src/pactown/registry/server.py', 'main', 4, 1, 4).
python_function('src/pactown/runner_api.py', '_dns_label', 2, 1, 1).
python_function('src/pactown/runner_api.py', '_validate_service_id', 1, 5, 1).
python_function('src/pactown/runner_api.py', '_service_name_for', 1, 1, 1).
python_function('src/pactown/runner_api.py', '_validate_rel_path', 1, 5, 5).
python_function('src/pactown/runner_api.py', '_resolve_in_dir', 2, 2, 3).
python_function('src/pactown/runner_api.py', 'create_runner_api', 0, 1, 47).
python_function('src/pactown/runner_api.py', 'create_app', 0, 1, 3).
python_function('src/pactown/runner_api.py', 'main', 0, 1, 4).
python_function('src/pactown/runner_types.py', 'kill_process_on_port', 2, 25, 12).
python_function('src/pactown/sandbox_helpers.py', '_ui_log_level', 0, 7, 4).
python_function('src/pactown/sandbox_helpers.py', '_should_emit_to_ui', 1, 2, 5).
python_function('src/pactown/sandbox_helpers.py', '_call_on_log', 3, 6, 6).
python_function('src/pactown/sandbox_helpers.py', '_filter_runtime_env', 1, 9, 5).
python_function('src/pactown/sandbox_helpers.py', '_sanitize_inherited_env', 2, 16, 12).
python_function('src/pactown/sandbox_helpers.py', '_escape_dotenv_value', 1, 1, 2).
python_function('src/pactown/sandbox_helpers.py', '_write_dotenv_file', 2, 8, 9).
python_function('src/pactown/sandbox_helpers.py', '_heartbeat', 0, 4, 5).
python_function('src/pactown/sandbox_helpers.py', '_beat_every_s', 0, 2, 4).
python_function('src/pactown/sandbox_helpers.py', '_path_debug', 1, 7, 7).
python_function('src/pactown/sandbox_manager.py', '_sandbox_fallback_ids', 0, 3, 3).
python_function('src/pactown/sandbox_manager.py', '_chown_sandbox_tree', 3, 11, 7).
python_function('src/pactown/sandbox_manager.py', '_detect_web_preview_needed', 4, 16, 6).
python_function('src/pactown/sandbox_manager.py', '_install_system_deps', 2, 11, 8).
python_function('src/pactown/sandbox_manager.py', '_inject_electron_web_polyfill', 3, 18, 7).
python_function('src/pactown/sandbox_manager.py', '_build_web_preview_cmd', 4, 14, 13).
python_function('src/pactown/sandbox_manager.py', '_find_web_assets_dir', 1, 5, 2).
python_function('src/pactown/security.py', 'get_security_policy', 0, 2, 1).
python_function('src/pactown/security.py', 'set_security_policy', 1, 1, 0).
python_function('src/pactown/targets.py', 'get_framework_meta', 1, 2, 3).
python_function('src/pactown/targets.py', 'list_frameworks', 1, 4, 2).
python_function('src/pactown/targets.py', '_to_int', 1, 3, 1).
python_function('src/pactown/targets.py', 'infer_target_from_deps', 1, 5, 6).
python_function('src/pactown/user_isolation.py', '_sanitize_gecos', 1, 3, 4).
python_function('src/pactown/user_isolation.py', 'get_isolation_manager', 0, 3, 5).
python_function('tests/conftest.py', 'async_test', 1, 1, 3).
python_function('tests/conftest.py', 'anyio_backend', 0, 1, 0).
python_function('tests/test_ansible.py', '_deploy_config', 0, 1, 3).
python_function('tests/test_ansible.py', 'test_runtime_type_ansible_exists', 0, 2, 0).
python_function('tests/test_ansible.py', 'test_runtime_type_ansible_in_enum', 0, 2, 0).
python_function('tests/test_ansible.py', '_docker_available', 0, 2, 1).
python_function('tests/test_ansible.py', '_docker_run', 5, 1, 1).
python_function('tests/test_ansible.py', '_docker_run_script', 6, 6, 2).
python_function('tests/test_ansible.py', '_should_skip_artifact_scan', 1, 5, 2).
python_function('tests/test_ansible.py', '_classify_artifact_size', 2, 10, 5).
python_function('tests/test_builders.py', 'test_get_builder_web', 0, 3, 2).
python_function('tests/test_builders.py', 'test_get_builder_desktop', 0, 3, 2).
python_function('tests/test_builders.py', 'test_get_builder_mobile', 0, 3, 2).
python_function('tests/test_builders.py', 'test_get_builder_for_target_none_defaults_to_web', 0, 2, 2).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop', 0, 2, 3).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron', 1, 7, 6).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_existing_package_json', 1, 5, 6).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_merges_main_into_minimal_package_json', 1, 7, 8).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_does_not_overwrite_existing_main', 1, 3, 6).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tauri', 1, 3, 5).
python_function('tests/test_builders.py', 'test_desktop_scaffold_pyinstaller', 1, 3, 4).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_clean', 0, 2, 1).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_dashes', 0, 2, 1).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_leading_digit', 0, 2, 1).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_special_chars', 0, 2, 1).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_empty_segments', 0, 2, 1).
python_function('tests/test_builders.py', 'test_sanitize_java_package_id_fallback', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor', 1, 9, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_sanitizes_dashed_appid', 1, 4, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_no_bundled_web_runtime', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_webdir_root', 1, 2, 5).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_webdir_dist', 1, 2, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_webdir_www', 1, 2, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_ios_target', 1, 3, 5).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_preserves_existing_deps', 1, 6, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_pins_latest_to_6x', 1, 4, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_migrates_storage_to_preferences', 1, 3, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_pins_ios_latest_to_6x', 1, 5, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_overrides_incompatible_platform_versions', 1, 4, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_updates_webdir_in_existing_config', 1, 2, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_kivy', 1, 4, 4).
python_function('tests/test_builders.py', 'test_web_builder_scaffold_noop', 1, 1, 2).
python_function('tests/test_builders.py', 'test_web_builder_build_no_cmd', 1, 3, 2).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_user_provided_main_js', 1, 4, 3).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_already_patched', 1, 2, 2).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_scaffolded_default', 1, 3, 4).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_desktop_notes_main_js', 1, 4, 4).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_no_main_js', 1, 2, 1).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_double_quotes', 1, 3, 3).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_es_module_single_quotes', 1, 4, 4).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_es_module_double_quotes', 1, 3, 3).
python_function('tests/test_builders.py', 'test_patch_no_sandbox_ultimate_fallback', 1, 4, 4).
python_function('tests/test_builders.py', 'test_generate_linux_launcher_creates_files', 1, 11, 7).
python_function('tests/test_builders.py', 'test_generate_linux_launcher_no_dist', 1, 2, 2).
python_function('tests/test_builders.py', 'test_generate_linux_launcher_no_appimage', 1, 2, 4).
python_function('tests/test_builders.py', 'test_build_result_defaults', 0, 3, 1).
python_function('tests/test_builders.py', 'test_mobile_scaffold_capacitor_updates_plugin_versions', 1, 8, 6).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tauri_window_dimensions', 1, 4, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tauri_default_dimensions', 1, 3, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tauri_does_not_overwrite_existing_config', 1, 3, 7).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tauri_bundle_identifier', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_pyqt', 1, 5, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_pyqt_with_icon', 1, 2, 3).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tkinter', 1, 3, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_tkinter_does_not_overwrite_existing_spec', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_flutter_desktop_noop', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_unknown_framework_noop', 1, 2, 3).
python_function('tests/test_builders.py', 'test_electron_builder_flags_linux_only', 0, 2, 1).
python_function('tests/test_builders.py', 'test_electron_builder_flags_empty_defaults_to_linux', 0, 2, 1).
python_function('tests/test_builders.py', 'test_electron_builder_flags_none_defaults_to_linux', 0, 2, 1).
python_function('tests/test_builders.py', 'test_electron_builder_flags_windows_skipped_on_linux_no_wine', 2, 3, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_windows_allowed_with_wine', 2, 3, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_mac_skipped_on_linux', 2, 3, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_mac_allowed_on_darwin', 2, 2, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_windows_on_windows', 2, 2, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_deduplicates', 0, 2, 2).
python_function('tests/test_builders.py', 'test_electron_builder_flags_aliases', 0, 2, 0).
python_function('tests/test_builders.py', 'test_filter_electron_builder_cmd_strips_windows_on_linux', 2, 4, 2).
python_function('tests/test_builders.py', 'test_filter_electron_builder_cmd_ensures_at_least_one_platform', 2, 2, 2).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_electron_linux', 0, 3, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_electron_multi_target', 2, 3, 2).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_tauri', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_pyinstaller', 0, 4, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_tkinter', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_pyqt', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_flutter_linux', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_flutter_windows', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_flutter_macos', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_default_build_cmd_unknown_framework', 0, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_electron_appimage', 1, 4, 3).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_electron_dmg', 1, 2, 5).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_electron_snap', 1, 2, 5).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_electron_run_sh', 1, 4, 3).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_tauri', 1, 3, 5).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_pyinstaller', 1, 4, 3).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_pyqt', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_tkinter', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_flutter', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_empty', 1, 2, 1).
python_function('tests/test_builders.py', 'test_desktop_collect_artifacts_unknown_framework_fallback', 1, 2, 4).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_build_targets', 1, 7, 5).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_move_electron_to_dev_deps', 1, 7, 7).
python_function('tests/test_builders.py', 'test_desktop_scaffold_electron_ensure_dev_deps_added', 1, 5, 6).
python_function('tests/test_builders.py', 'test_desktop_build_no_cmd_returns_failure', 0, 3, 3).
python_function('tests/test_builders.py', 'test_mobile_scaffold_react_native', 1, 4, 5).
python_function('tests/test_builders.py', 'test_mobile_scaffold_react_native_default_display_name', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_scaffold_react_native_does_not_overwrite', 1, 3, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_kivy_app_id', 1, 2, 3).
python_function('tests/test_builders.py', 'test_mobile_scaffold_kivy_no_fullscreen', 1, 2, 3).
python_function('tests/test_builders.py', 'test_mobile_scaffold_kivy_does_not_overwrite', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_scaffold_kivy_has_required_sections', 1, 5, 3).
python_function('tests/test_builders.py', 'test_mobile_scaffold_flutter_noop', 1, 3, 6).
python_function('tests/test_builders.py', 'test_mobile_scaffold_unknown_framework_noop', 1, 2, 3).
python_function('tests/test_builders.py', 'test_mobile_capacitor_webdir_priority_dist_over_www', 1, 3, 3).
python_function('tests/test_builders.py', 'test_mobile_capacitor_webdir_priority_build', 1, 2, 3).
python_function('tests/test_builders.py', 'test_mobile_capacitor_webdir_priority_public', 1, 2, 3).
python_function('tests/test_builders.py', 'test_mobile_capacitor_webdir_no_index_defaults_to_dist', 1, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_capacitor_android', 0, 3, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_capacitor_ios', 0, 3, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_react_native_android', 0, 3, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_react_native_ios', 0, 3, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_flutter_android', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_flutter_ios', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_kivy_android', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_kivy_ios', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_unknown_framework', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_default_build_cmd_empty_targets_defaults_android', 0, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_capacitor_apk', 1, 3, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_capacitor_ipa', 1, 3, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_capacitor_both', 1, 4, 3).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_react_native_apk', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_react_native_ipa', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_flutter_apk', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_flutter_ipa', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_kivy_apk', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_kivy_aab', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_empty', 1, 2, 1).
python_function('tests/test_builders.py', 'test_mobile_collect_artifacts_unknown_framework_fallback', 1, 2, 4).
python_function('tests/test_builders.py', 'test_mobile_build_no_cmd_returns_failure', 0, 3, 3).
python_function('tests/test_builders.py', 'test_mobile_ensure_cap_platforms_skips_existing_dir', 1, 1, 5).
python_function('tests/test_builders.py', 'test_mobile_ensure_cap_platforms_runs_cap_add', 1, 3, 5).
python_function('tests/test_builders.py', 'test_mobile_ensure_cap_platforms_multiple_targets', 1, 5, 3).
python_function('tests/test_builders.py', 'test_mobile_ensure_cap_platforms_partial_existing', 1, 3, 4).
python_function('tests/test_builders.py', 'test_mobile_build_capacitor_calls_ensure_platforms', 1, 2, 4).
python_function('tests/test_builders.py', 'test_web_builder_platform_name', 0, 2, 1).
python_function('tests/test_builders.py', 'test_web_builder_scaffold_multiple_frameworks', 1, 3, 4).
python_function('tests/test_builders.py', 'test_web_builder_build_result_structure', 1, 5, 3).
python_function('tests/test_builders.py', 'test_build_result_all_fields', 0, 7, 3).
python_function('tests/test_builders.py', 'test_build_result_failure', 0, 5, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_desktop_electron', 0, 11, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_mobile_capacitor', 0, 7, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_mobile_react_native', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_mobile_flutter', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_mobile_kivy', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_desktop_tauri', 0, 3, 2).
python_function('tests/test_builders.py', 'test_target_config_from_dict_desktop_pyinstaller', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_desktop_pyqt', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_desktop_tkinter', 0, 2, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_web_default', 0, 6, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_unknown_platform_defaults_web', 0, 2, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_targets_as_csv_string', 0, 2, 1).
python_function('tests/test_builders.py', 'test_target_config_from_dict_extra_keys_preserved', 0, 2, 1).
python_function('tests/test_builders.py', 'test_target_config_from_yaml_body', 0, 4, 1).
python_function('tests/test_builders.py', 'test_target_config_from_yaml_body_invalid', 0, 2, 1).
python_function('tests/test_builders.py', 'test_effective_build_targets_desktop_explicit', 0, 2, 2).
python_function('tests/test_builders.py', 'test_effective_build_targets_desktop_default', 0, 2, 2).
python_function('tests/test_builders.py', 'test_effective_build_targets_mobile_explicit', 0, 2, 2).
python_function('tests/test_builders.py', 'test_effective_build_targets_mobile_default', 0, 2, 2).
python_function('tests/test_builders.py', 'test_effective_build_targets_web_empty', 0, 2, 2).
python_function('tests/test_builders.py', 'test_target_config_framework_meta_electron', 0, 4, 1).
python_function('tests/test_builders.py', 'test_target_config_framework_meta_capacitor', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_framework_meta_pyinstaller', 0, 3, 1).
python_function('tests/test_builders.py', 'test_target_config_framework_meta_none', 0, 2, 1).
python_function('tests/test_builders.py', 'test_framework_registry_has_all_desktop_frameworks', 0, 2, 3).
python_function('tests/test_builders.py', 'test_framework_registry_has_all_mobile_frameworks', 0, 2, 3).
python_function('tests/test_builders.py', 'test_framework_registry_desktop_platforms', 0, 3, 0).
python_function('tests/test_builders.py', 'test_framework_registry_mobile_platforms', 0, 3, 0).
python_function('tests/test_builders.py', 'test_framework_registry_all_have_build_cmd', 0, 3, 1).
python_function('tests/test_builders.py', 'test_framework_registry_all_have_artifact_patterns', 0, 3, 1).
python_function('tests/test_builders.py', 'test_framework_registry_node_frameworks', 0, 3, 0).
python_function('tests/test_builders.py', 'test_framework_registry_python_frameworks', 0, 3, 0).
python_function('tests/test_builders.py', 'test_get_framework_meta_case_insensitive', 0, 4, 1).
python_function('tests/test_builders.py', 'test_get_framework_meta_unknown', 0, 4, 1).
python_function('tests/test_builders.py', 'test_list_frameworks_all', 0, 2, 2).
python_function('tests/test_builders.py', 'test_list_frameworks_desktop_only', 0, 3, 3).
python_function('tests/test_builders.py', 'test_list_frameworks_mobile_only', 0, 3, 3).
python_function('tests/test_builders.py', 'test_infer_target_electron', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_tauri', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_pyinstaller', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_pyqt', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_tkinter', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_capacitor', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_react_native', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_expo', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_buildozer', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_flutter', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_web_default', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_empty_deps', 0, 2, 1).
python_function('tests/test_builders.py', 'test_infer_target_mobile_over_desktop_when_both_hinted', 0, 2, 1).
python_function('tests/test_builders.py', 'test_get_builder_for_target_mobile_capacitor', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_mobile_react_native', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_mobile_flutter', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_mobile_kivy', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop_electron', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop_tauri', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop_pyinstaller', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop_pyqt', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_desktop_tkinter', 0, 2, 3).
python_function('tests/test_builders.py', 'test_get_builder_for_target_web_fastapi', 0, 2, 3).
python_function('tests/test_config.py', 'test_dependency_config_from_string', 0, 3, 1).
python_function('tests/test_config.py', 'test_dependency_config_from_dict', 0, 5, 1).
python_function('tests/test_config.py', 'test_service_config_from_dict', 0, 7, 2).
python_function('tests/test_config.py', 'test_ecosystem_config_from_dict', 0, 6, 2).
python_function('tests/test_config.py', 'test_ecosystem_config_auto_port', 0, 3, 1).
python_function('tests/test_config.py', 'test_ecosystem_config_from_yaml', 0, 5, 6).
python_function('tests/test_config.py', 'test_ecosystem_config_to_dict', 0, 3, 3).
python_function('tests/test_config.py', 'test_load_config_file_not_found', 0, 1, 2).
python_function('tests/test_config.py', 'test_registry_config_defaults', 0, 4, 1).
python_function('tests/test_config.py', 'test_cache_config_from_env_prefers_pactown_prefixed_vars', 1, 3, 2).
python_function('tests/test_config.py', 'test_cache_config_to_env_sets_pip_extra_when_missing', 0, 3, 2).
python_function('tests/test_config.py', 'test_cache_config_to_docker_build_args_maps_apt_proxy', 0, 4, 2).
python_function('tests/test_config.py', 'test_cache_config_from_env_reads_pip_timeout_and_retries', 1, 3, 2).
python_function('tests/test_config.py', 'test_cache_config_to_env_includes_timeout_and_retries', 0, 3, 2).
python_function('tests/test_config.py', 'test_cache_config_to_docker_build_args_includes_timeout_and_retries', 0, 3, 2).
python_function('tests/test_cross_platform.py', '_deploy_config', 0, 1, 4).
python_function('tests/test_cross_platform.py', '_create_artifacts', 2, 2, 3).
python_function('tests/test_deploy_dockerfile.py', 'test_python_dockerfile_healthcheck_does_not_use_curl', 0, 5, 6).
python_function('tests/test_deploy_dockerfile.py', 'test_python_dockerfile_supports_pip_timeout_and_retries_build_args', 0, 5, 6).
python_function('tests/test_deploy_dockerfile.py', 'test_node_dockerfile_falls_back_when_package_lock_missing', 0, 8, 6).
python_function('tests/test_deploy_dockerfile.py', 'test_markpact_readme_python_materializes_and_generates_cmd_from_run_block', 0, 6, 11).
python_function('tests/test_deploy_dockerfile.py', 'test_markpact_readme_node_materializes_package_json_and_generates_cmd_from_run_block', 0, 7, 11).
python_function('tests/test_deploy_dockerfile.py', 'test_markpact_readme_static_web_no_deps_generates_cmd_from_run_block', 0, 5, 11).
python_function('tests/test_deploy_platforms.py', '_readme', 1, 1, 1).
python_function('tests/test_deploy_platforms.py', '_sandbox_and_manager', 1, 1, 1).
python_function('tests/test_deploy_platforms.py', '_create_sandbox_from_readme', 6, 1, 6).
python_function('tests/test_e2e_build.py', '_write_readme', 2, 1, 2).
python_function('tests/test_e2e_build.py', '_parse_and_resolve', 1, 1, 4).
python_function('tests/test_e2e_build_extended.py', '_write_readme', 2, 1, 2).
python_function('tests/test_e2e_build_extended.py', '_parse_and_resolve', 1, 1, 4).
python_function('tests/test_e2e_deploy_desktop_mobile.py', '_make_proc_mock', 0, 2, 3).
python_function('tests/test_e2e_deploy_desktop_mobile.py', '_fake_popen_factory', 1, 1, 4).
python_function('tests/test_e2e_deploy_desktop_mobile.py', '_write_readme', 2, 1, 2).
python_function('tests/test_e2e_deploy_desktop_mobile.py', '_headless_env', 1, 2, 3).
python_function('tests/test_e2e_deploy_desktop_mobile.py', 'manager', 2, 2, 4).
python_function('tests/test_e2e_deploy_desktop_mobile.py', '_deploy', 5, 1, 6).
python_function('tests/test_electron_xvfb.py', '_make_proc_mock', 0, 2, 3).
python_function('tests/test_electron_xvfb.py', 'manager', 2, 2, 4).
python_function('tests/test_electron_xvfb.py', 'readme_path', 1, 1, 2).
python_function('tests/test_electron_xvfb.py', 'service', 1, 1, 3).
python_function('tests/test_electron_xvfb.py', '_fake_popen_factory', 1, 1, 4).
python_function('tests/test_iac_manifest.py', 'test_create_sandbox_writes_iac_manifest_and_compose_and_dockerfile', 0, 10, 10).
python_function('tests/test_iac_manifest.py', 'test_create_sandbox_node_inferred_writes_manifest', 0, 4, 10).
python_function('tests/test_markpact_blocks.py', 'test_parse_blocks_new_format_includes_lang', 0, 7, 3).
python_function('tests/test_markpact_blocks.py', 'test_parse_blocks_old_format_is_supported', 0, 7, 3).
python_function('tests/test_markpact_blocks.py', 'test_parse_blocks_run_block_new_format', 0, 6, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_explicit_block', 0, 2, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_from_target_framework', 0, 2, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_file_heuristic_main_py', 0, 2, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_file_heuristic_index_js', 0, 2, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_returns_none_when_no_hint', 0, 2, 2).
python_function('tests/test_markpact_blocks.py', 'test_extract_run_command_explicit_overrides_framework', 0, 2, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_parse_target_block_yaml', 0, 9, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_extract_target_config_desktop', 0, 5, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_extract_target_config_mobile', 0, 5, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_extract_target_config_none_when_missing', 0, 2, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_parse_build_block', 0, 5, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_extract_build_cmd', 0, 2, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_extract_build_cmd_none_when_missing', 0, 2, 2).
python_function('tests/test_markpact_target_blocks.py', 'test_full_desktop_markpact', 0, 20, 5).
python_function('tests/test_markpact_target_blocks.py', 'test_full_mobile_markpact', 0, 6, 3).
python_function('tests/test_markpact_target_blocks.py', 'test_get_meta_value', 0, 5, 3).
python_function('tests/test_network.py', 'test_port_allocator_allocate', 0, 2, 2).
python_function('tests/test_network.py', 'test_port_allocator_preferred_port', 0, 2, 3).
python_function('tests/test_network.py', 'test_port_allocator_release', 0, 8, 8).
python_function('tests/test_network.py', 'test_service_endpoint', 0, 3, 1).
python_function('tests/test_network.py', 'test_service_registry_register', 0, 4, 5).
python_function('tests/test_network.py', 'test_service_registry_get', 0, 4, 6).
python_function('tests/test_network.py', 'test_service_registry_get_url', 0, 2, 6).
python_function('tests/test_network.py', 'test_service_registry_environment', 0, 5, 7).
python_function('tests/test_network.py', 'test_service_registry_unregister', 0, 3, 7).
python_function('tests/test_network.py', 'test_service_registry_dynamic_port', 0, 2, 5).
python_function('tests/test_network.py', 'test_find_free_port', 0, 3, 2).
python_function('tests/test_network.py', 'test_check_port', 0, 2, 2).
python_function('tests/test_node_cache.py', '_make_pkg_json', 3, 3, 1).
python_function('tests/test_node_cache.py', '_populate_node_modules', 2, 3, 3).
python_function('tests/test_parallel.py', 'test_run_parallel_basic', 0, 6, 3).
python_function('tests/test_parallel.py', 'test_run_parallel_with_error', 0, 4, 2).
python_function('tests/test_parallel.py', 'test_run_parallel_timing', 0, 4, 6).
python_function('tests/test_parallel.py', 'test_run_in_dependency_waves', 0, 5, 8).
python_function('tests/test_parallel.py', 'test_run_in_dependency_waves_diamond', 0, 4, 6).
python_function('tests/test_parallel.py', 'test_task_result_dataclass', 0, 6, 1).
python_function('tests/test_platform.py', 'test_normalize_host_strips_scheme_and_port', 0, 2, 1).
python_function('tests/test_platform.py', 'test_normalize_domain_strips_www_and_scheme', 0, 2, 1).
python_function('tests/test_platform.py', 'test_build_project_host_dash_separator_normalizes_username', 0, 2, 1).
python_function('tests/test_platform.py', 'test_build_project_host_dot_separator_normalizes_username', 0, 2, 1).
python_function('tests/test_platform.py', 'test_parse_project_host', 1, 4, 2).
python_function('tests/test_platform.py', 'test_build_project_subdomain_limits_length', 0, 3, 3).
python_function('tests/test_platform.py', 'test_build_service_subdomain_dash', 0, 2, 1).
python_function('tests/test_platform.py', 'test_build_service_subdomain_dot', 0, 2, 1).
python_function('tests/test_quadlet_security.py', 'temp_dir', 0, 1, 2).
python_function('tests/test_quadlet_security.py', 'mock_systemctl', 0, 1, 2).
python_function('tests/test_registry.py', 'test_artifact_version_to_dict', 0, 4, 2).
python_function('tests/test_registry.py', 'test_artifact_version_from_dict', 0, 3, 1).
python_function('tests/test_registry.py', 'test_artifact_full_name', 0, 2, 1).
python_function('tests/test_registry.py', 'test_artifact_add_version', 0, 3, 3).
python_function('tests/test_registry.py', 'test_artifact_get_version', 0, 5, 4).
python_function('tests/test_registry.py', 'test_registry_storage_save_and_get', 0, 4, 8).
python_function('tests/test_registry.py', 'test_registry_storage_list', 0, 5, 7).
python_function('tests/test_registry.py', 'test_registry_storage_delete', 0, 4, 7).
python_function('tests/test_registry.py', 'test_registry_storage_search', 0, 4, 7).
python_function('tests/test_registry.py', 'test_registry_storage_persistence', 0, 3, 8).
python_function('tests/test_resolver.py', 'make_config', 1, 3, 5).
python_function('tests/test_resolver.py', 'test_startup_order_no_deps', 0, 2, 4).
python_function('tests/test_resolver.py', 'test_startup_order_linear', 0, 3, 4).
python_function('tests/test_resolver.py', 'test_startup_order_diamond', 0, 4, 4).
python_function('tests/test_resolver.py', 'test_circular_dependency_detection', 0, 1, 4).
python_function('tests/test_resolver.py', 'test_shutdown_order', 0, 2, 6).
python_function('tests/test_resolver.py', 'test_resolve_service_deps', 0, 4, 4).
python_function('tests/test_resolver.py', 'test_get_environment', 0, 4, 3).
python_function('tests/test_resolver.py', 'test_validate_missing_dep', 0, 3, 4).
python_function('tests/test_resolver.py', 'test_print_graph', 0, 3, 3).
python_function('tests/test_runner_api.py', '_sample_markdown', 0, 1, 0).
python_function('tests/test_runner_api.py', 'test_validate_ok', 1, 5, 8).
python_function('tests/test_runner_api.py', 'test_run_fails_fast_on_missing_required_env_vars', 1, 5, 8).
python_function('tests/test_runner_api.py', 'test_run_passes_pip_timeout_and_retries_to_pip_install', 2, 9, 22).
python_function('tests/test_runner_api.py', 'test_sandbox_prepare_and_file_ops', 1, 15, 11).
python_function('tests/test_runner_api.py', 'test_status_filtering', 1, 3, 7).
python_function('tests/test_runner_api.py', 'test_run_failure_includes_error_report_md', 2, 8, 15).
python_function('tests/test_runner_api.py', 'test_run_stream_failure_includes_error_report_md', 2, 8, 18).
python_function('tests/test_sandbox_manager_env_injection.py', 'test_sandbox_manager_passes_env_to_pip_install', 2, 3, 12).
python_function('tests/test_sandbox_manager_node_deps.py', 'test_node_project_uses_npm_instead_of_pip_even_if_deps_lang_is_wrong', 2, 4, 11).
python_function('tests/test_sandbox_manager_node_deps.py', 'test_node_deps_block_creates_package_json_and_calls_npm', 2, 4, 12).
python_function('tests/test_sandbox_manager_node_run_env.py', 'test_sandbox_manager_passes_env_to_node_run', 2, 7, 13).
python_function('tests/test_sandbox_manager_venv_heal.py', 'test_self_heal_corrupted_cache', 1, 19, 26).
python_function('tests/test_security.py', '_pip_audit_available', 0, 2, 1).
python_function('tests/test_service_runner_fast_run_fallback.py', 'test_fast_run_fallback_sets_serviceconfig_readme_and_cleans_temp_file', 2, 6, 12).
python_function('tests/test_service_runner_validation.py', 'test_validate_content_dependency_mismatch', 0, 9, 4).
python_function('tests/test_targets.py', 'test_target_platform_values', 0, 4, 0).
python_function('tests/test_targets.py', 'test_target_config_from_yaml_desktop', 0, 9, 1).
python_function('tests/test_targets.py', 'test_target_config_from_yaml_mobile', 0, 8, 1).
python_function('tests/test_targets.py', 'test_target_config_defaults_to_web', 0, 5, 1).
python_function('tests/test_targets.py', 'test_target_config_from_dict_targets_as_string', 0, 2, 1).
python_function('tests/test_targets.py', 'test_target_config_effective_build_targets_desktop', 0, 2, 2).
python_function('tests/test_targets.py', 'test_target_config_effective_build_targets_mobile', 0, 2, 2).
python_function('tests/test_targets.py', 'test_target_config_effective_build_targets_explicit', 0, 2, 2).
python_function('tests/test_targets.py', 'test_target_config_extra_keys_preserved', 0, 2, 1).
python_function('tests/test_targets.py', 'test_get_framework_meta_electron', 0, 4, 1).
python_function('tests/test_targets.py', 'test_get_framework_meta_capacitor', 0, 4, 1).
python_function('tests/test_targets.py', 'test_get_framework_meta_pyinstaller', 0, 4, 1).
python_function('tests/test_targets.py', 'test_get_framework_meta_unknown', 0, 2, 1).
python_function('tests/test_targets.py', 'test_list_frameworks_all', 0, 2, 2).
python_function('tests/test_targets.py', 'test_list_frameworks_desktop_only', 0, 3, 3).
python_function('tests/test_targets.py', 'test_list_frameworks_mobile_only', 0, 3, 3).
python_function('tests/test_targets.py', 'test_infer_desktop_from_electron_dep', 0, 2, 1).
python_function('tests/test_targets.py', 'test_infer_mobile_from_capacitor_dep', 0, 2, 1).
python_function('tests/test_targets.py', 'test_infer_web_from_fastapi_dep', 0, 2, 1).
python_function('tests/test_targets.py', 'test_infer_web_from_empty_deps', 0, 2, 1).
python_function('tests/test_targets.py', 'test_infer_mobile_over_desktop_when_both', 0, 2, 1).
python_function('tests/test_user_isolation_manager.py', 'test_sanitize_gecos_removes_colon_and_control_chars', 0, 4, 2).
python_function('tests/test_user_isolation_manager.py', 'test_get_or_create_user_non_root_virtual_user', 2, 5, 6).
python_function('tests/test_user_isolation_manager.py', 'test_get_or_create_user_reuses_existing_linux_user', 2, 5, 6).
python_function('tests/test_user_isolation_manager.py', 'test_get_or_create_user_root_creates_user_with_sanitized_comment', 2, 11, 10).
python_function('tests/test_user_isolation_manager.py', 'test_delete_user_root_builds_userdel_cmd', 2, 3, 7).
python_function('tools/sync_pactown_com_dependency.py', '_read_pactown_version', 1, 2, 5).
python_function('tools/sync_pactown_com_dependency.py', '_update_requirements_pin', 1, 8, 9).
python_function('tools/sync_pactown_com_dependency.py', 'main', 0, 8, 14).
python_function('tools/validate_artifacts_docker.py', 'docker_available', 0, 2, 1).
python_function('tools/validate_artifacts_docker.py', 'docker_run', 6, 6, 4).
python_function('tools/validate_artifacts_docker.py', '_py_script', 1, 1, 3).
python_function('tools/validate_artifacts_docker.py', '_py_yaml_script', 1, 1, 3).
python_function('tools/validate_artifacts_docker.py', '_reg', 3, 1, 0).
python_function('tools/validate_artifacts_docker.py', 'collect_artifacts', 1, 6, 7).
python_function('tools/validate_artifacts_docker.py', 'get_validator', 1, 5, 2).
python_function('tools/validate_artifacts_docker.py', '_find_service_dir', 2, 1, 1).
python_function('tools/validate_artifacts_docker.py', 'validate_artifact', 4, 6, 9).
python_function('tools/validate_artifacts_docker.py', 'main', 0, 17, 24).

% ── Python Classes ───────────────────────────────────────
python_class('src/pactown/builders/base.py', 'BuildError').
python_class('src/pactown/builders/base.py', 'BuildResult').
python_class('src/pactown/builders/base.py', 'Builder').
python_method('Builder', 'platform_name', 0, 1, 0).
python_method('Builder', 'scaffold', 1, 1, 0).
python_method('Builder', 'build', 1, 1, 0).
python_method('Builder', '_log', 2, 3, 1).
python_method('Builder', '_run_shell', 1, 13, 16).
python_class('src/pactown/builders/desktop.py', 'DesktopBuilder').
python_method('DesktopBuilder', 'platform_name', 0, 1, 0).
python_method('DesktopBuilder', 'scaffold', 1, 5, 6).
python_method('DesktopBuilder', 'build', 1, 11, 13).
python_method('DesktopBuilder', '_electron_already_scaffolded', 1, 5, 4).
python_method('DesktopBuilder', '_patch_electron_no_sandbox', 3, 15, 7).
python_method('DesktopBuilder', '_scaffold_electron', 1, 19, 10).
python_method('DesktopBuilder', '_move_to_dev_deps', 2, 4, 5).
python_method('DesktopBuilder', '_ensure_electron_dev_deps', 1, 3, 2).
python_method('DesktopBuilder', '_scaffold_tauri', 1, 5, 6).
python_method('DesktopBuilder', '_scaffold_python_desktop', 1, 5, 4).
python_method('DesktopBuilder', '_filter_electron_builder_cmd', 1, 10, 7).
python_method('DesktopBuilder', '_electron_builder_flags', 1, 12, 5).
python_method('DesktopBuilder', '_default_build_cmd', 3, 7, 4).
python_method('DesktopBuilder', 'build_parallel', 1, 18, 21).
python_method('DesktopBuilder', '_generate_linux_launcher', 3, 3, 7).
python_method('DesktopBuilder', '_collect_artifacts', 2, 4, 4).
python_class('src/pactown/builders/mobile.py', 'MobileBuilder').
python_method('MobileBuilder', 'platform_name', 0, 1, 0).
python_method('MobileBuilder', 'scaffold', 1, 6, 6).
python_method('MobileBuilder', 'build', 1, 10, 12).
python_method('MobileBuilder', '_scaffold_capacitor', 1, 24, 15).
python_method('MobileBuilder', '_resolve_cap_web_dir', 1, 4, 1).
python_method('MobileBuilder', '_scaffold_react_native', 1, 3, 5).
python_method('MobileBuilder', '_scaffold_kivy', 1, 8, 6).
python_method('MobileBuilder', '_ensure_cap_platforms', 2, 6, 6).
python_method('MobileBuilder', '_default_build_cmd', 2, 10, 2).
python_method('MobileBuilder', '_collect_artifacts', 2, 4, 4).
python_class('src/pactown/builders/web.py', 'WebBuilder').
python_method('WebBuilder', 'platform_name', 0, 1, 0).
python_method('WebBuilder', 'scaffold', 1, 1, 1).
python_method('WebBuilder', 'build', 1, 4, 5).
python_class('src/pactown/config.py', 'DependencyConfig').
python_method('DependencyConfig', 'from_dict', 2, 3, 4).
python_class('src/pactown/config.py', 'ServiceConfig').
python_method('ServiceConfig', 'from_dict', 3, 3, 7).
python_class('src/pactown/config.py', 'RegistryConfig').
python_class('src/pactown/config.py', 'CacheConfig').
python_method('CacheConfig', 'from_env', 2, 12, 5).
python_method('CacheConfig', '_to_mapping', 0, 11, 1).
python_method('CacheConfig', 'to_env', 0, 1, 1).
python_method('CacheConfig', 'to_docker_build_args', 0, 1, 1).
python_class('src/pactown/config.py', 'EcosystemConfig').
python_method('EcosystemConfig', 'from_yaml', 2, 1, 3).
python_method('EcosystemConfig', 'from_dict', 3, 3, 6).
python_method('EcosystemConfig', 'to_dict', 0, 6, 1).
python_method('EcosystemConfig', 'to_yaml', 1, 1, 3).
python_class('src/pactown/deploy/ansible.py', 'AnsibleConfig').
python_method('AnsibleConfig', 'for_local', 1, 1, 1).
python_method('AnsibleConfig', 'for_remote', 4, 1, 1).
python_class('src/pactown/deploy/ansible.py', 'AnsibleBackend').
python_method('AnsibleBackend', '__init__', 2, 3, 4).
python_method('AnsibleBackend', 'runtime_type', 0, 1, 0).
python_method('AnsibleBackend', 'is_available', 0, 2, 1).
python_method('AnsibleBackend', 'build_image', 5, 3, 5).
python_method('AnsibleBackend', 'push_image', 2, 3, 4).
python_method('AnsibleBackend', 'deploy', 5, 3, 5).
python_method('AnsibleBackend', 'stop', 1, 2, 4).
python_method('AnsibleBackend', 'logs', 2, 3, 2).
python_method('AnsibleBackend', 'status', 1, 4, 2).
python_method('AnsibleBackend', '_write_playbook', 2, 1, 3).
python_method('AnsibleBackend', '_write_inventory', 0, 1, 4).
python_method('AnsibleBackend', 'write_all', 0, 1, 4).
python_method('AnsibleBackend', '_run_playbook', 1, 8, 6).
python_class('src/pactown/deploy/base.py', 'RuntimeType').
python_class('src/pactown/deploy/base.py', 'DeploymentMode').
python_class('src/pactown/deploy/base.py', 'DeploymentConfig').
python_method('DeploymentConfig', 'for_production', 1, 1, 1).
python_method('DeploymentConfig', 'for_development', 1, 1, 1).
python_class('src/pactown/deploy/base.py', 'DeploymentResult').
python_class('src/pactown/deploy/base.py', 'DeploymentBackend').
python_method('DeploymentBackend', '__init__', 1, 1, 0).
python_method('DeploymentBackend', 'runtime_type', 0, 1, 0).
python_method('DeploymentBackend', 'is_available', 0, 1, 0).
python_method('DeploymentBackend', 'build_image', 5, 1, 0).
python_method('DeploymentBackend', 'push_image', 2, 1, 0).
python_method('DeploymentBackend', 'deploy', 5, 1, 0).
python_method('DeploymentBackend', 'stop', 1, 1, 0).
python_method('DeploymentBackend', 'logs', 2, 1, 0).
python_method('DeploymentBackend', 'status', 1, 1, 0).
python_method('DeploymentBackend', 'generate_dockerfile', 4, 1, 2).
python_method('DeploymentBackend', '_create_dockerfile', 3, 5, 6).
python_method('DeploymentBackend', '_create_node_dockerfile', 2, 3, 2).
python_class('src/pactown/deploy/compose.py', 'ComposeService').
python_class('src/pactown/deploy/compose.py', 'ComposeGenerator').
python_method('ComposeGenerator', '__init__', 3, 1, 1).
python_method('ComposeGenerator', 'generate', 2, 6, 6).
python_method('ComposeGenerator', '_create_service', 2, 18, 8).
python_method('ComposeGenerator', '_create_registry_service', 0, 1, 0).
python_method('ComposeGenerator', 'generate_override', 2, 5, 4).
python_method('ComposeGenerator', 'generate_production', 2, 3, 4).
python_class('src/pactown/deploy/docker.py', 'DockerBackend').
python_method('DockerBackend', 'runtime_type', 0, 1, 0).
python_method('DockerBackend', 'is_available', 0, 2, 1).
python_method('DockerBackend', 'build_image', 5, 9, 10).
python_method('DockerBackend', 'push_image', 2, 4, 3).
python_method('DockerBackend', 'deploy', 5, 16, 7).
python_method('DockerBackend', 'stop', 1, 2, 2).
python_method('DockerBackend', 'logs', 2, 1, 2).
python_method('DockerBackend', 'status', 1, 3, 3).
python_class('src/pactown/deploy/kubernetes.py', 'KubernetesBackend').
python_method('KubernetesBackend', '__init__', 2, 1, 2).
python_method('KubernetesBackend', 'runtime_type', 0, 1, 0).
python_method('KubernetesBackend', '_kubectl', 0, 2, 2).
python_method('KubernetesBackend', 'is_available', 0, 2, 1).
python_method('KubernetesBackend', 'build_image', 5, 9, 9).
python_method('KubernetesBackend', 'push_image', 2, 4, 3).
python_method('KubernetesBackend', 'deploy', 5, 4, 4).
python_method('KubernetesBackend', 'stop', 1, 2, 2).
python_method('KubernetesBackend', 'logs', 2, 1, 2).
python_method('KubernetesBackend', 'status', 1, 3, 3).
python_method('KubernetesBackend', 'generate_manifests', 6, 4, 1).
python_method('KubernetesBackend', 'generate_hpa', 4, 1, 0).
python_method('KubernetesBackend', 'save_manifests', 3, 3, 6).
python_class('src/pactown/deploy/podman.py', 'PodmanBackend').
python_method('PodmanBackend', 'runtime_type', 0, 1, 0).
python_method('PodmanBackend', 'is_available', 0, 2, 1).
python_method('PodmanBackend', 'build_image', 5, 10, 10).
python_method('PodmanBackend', 'push_image', 2, 4, 3).
python_method('PodmanBackend', 'deploy', 5, 17, 7).
python_method('PodmanBackend', 'stop', 1, 2, 2).
python_method('PodmanBackend', 'logs', 2, 1, 2).
python_method('PodmanBackend', 'status', 1, 3, 3).
python_method('PodmanBackend', 'generate_systemd_unit', 2, 2, 0).
python_method('PodmanBackend', 'create_pod', 3, 3, 3).
python_class('src/pactown/deploy/quadlet.py', 'QuadletConfig').
python_method('QuadletConfig', 'full_domain', 0, 2, 1).
python_method('QuadletConfig', 'systemd_path', 0, 2, 2).
python_method('QuadletConfig', 'tenant_path', 0, 1, 0).
python_class('src/pactown/deploy/quadlet.py', 'QuadletUnit').
python_method('QuadletUnit', 'filename', 0, 1, 2).
python_method('QuadletUnit', 'save', 1, 1, 2).
python_class('src/pactown/deploy/quadlet.py', 'QuadletTemplates').
python_method('QuadletTemplates', 'container', 9, 18, 14).
python_method('QuadletTemplates', 'pod', 5, 4, 3).
python_method('QuadletTemplates', 'network', 6, 3, 2).
python_method('QuadletTemplates', 'volume', 3, 1, 2).
python_class('src/pactown/deploy/quadlet.py', 'QuadletBackend').
python_method('QuadletBackend', '__init__', 2, 2, 3).
python_method('QuadletBackend', 'runtime_type', 0, 1, 0).
python_method('QuadletBackend', 'is_available', 0, 5, 4).
python_method('QuadletBackend', 'get_quadlet_version', 0, 3, 2).
python_method('QuadletBackend', 'build_image', 5, 8, 10).
python_method('QuadletBackend', 'push_image', 2, 5, 3).
python_method('QuadletBackend', 'generate_quadlet_files', 7, 1, 2).
python_method('QuadletBackend', 'deploy', 5, 4, 5).
python_method('QuadletBackend', 'stop', 1, 4, 5).
python_method('QuadletBackend', 'logs', 2, 3, 4).
python_method('QuadletBackend', 'status', 1, 5, 6).
python_method('QuadletBackend', '_systemctl', 2, 3, 2).
python_method('QuadletBackend', 'list_services', 0, 3, 5).
python_class('src/pactown/deploy/quadlet_api.py', 'DeploymentRequest').
python_class('src/pactown/deploy/quadlet_api.py', 'ContainerRequest').
python_class('src/pactown/deploy/quadlet_api.py', 'TraefikRequest').
python_class('src/pactown/deploy/quadlet_api.py', 'DeploymentResponse').
python_class('src/pactown/deploy/quadlet_api.py', 'QuadletFileResponse').
python_class('src/pactown/deploy/quadlet_api.py', 'ServiceStatus').
python_class('src/pactown/deploy/quadlet_api.py', 'ListServicesResponse').
python_class('src/pactown/deploy/quadlet_shell.py', 'QuadletShell').
python_method('QuadletShell', '__init__', 3, 2, 7).
python_method('QuadletShell', 'do_status', 1, 2, 6).
python_method('QuadletShell', 'do_config', 1, 9, 4).
python_method('QuadletShell', 'do_generate', 1, 7, 12).
python_method('QuadletShell', 'do_generate_container', 1, 3, 9).
python_method('QuadletShell', 'do_generate_traefik', 1, 4, 8).
python_method('QuadletShell', 'do_list', 1, 4, 6).
python_method('QuadletShell', 'do_start', 1, 3, 2).
python_method('QuadletShell', 'do_stop', 1, 3, 2).
python_method('QuadletShell', 'do_restart', 1, 3, 2).
python_method('QuadletShell', 'do_logs', 1, 4, 6).
python_method('QuadletShell', 'do_reload', 1, 2, 2).
python_method('QuadletShell', 'do_deploy', 1, 7, 9).
python_method('QuadletShell', 'do_undeploy', 1, 4, 3).
python_method('QuadletShell', 'do_init', 1, 3, 6).
python_method('QuadletShell', 'do_export', 1, 5, 7).
python_method('QuadletShell', 'do_help', 1, 2, 4).
python_method('QuadletShell', 'do_quit', 1, 1, 1).
python_method('QuadletShell', 'do_exit', 1, 1, 1).
python_method('QuadletShell', 'do_EOF', 1, 1, 2).
python_method('QuadletShell', 'default', 1, 1, 1).
python_method('QuadletShell', 'emptyline', 0, 1, 0).
python_class('src/pactown/error_context.py', 'ErrorContextConfig').
python_class('src/pactown/events.py', 'EventType').
python_class('src/pactown/events.py', 'Event').
python_method('Event', 'to_dict', 0, 3, 2).
python_method('Event', 'from_dict', 2, 3, 5).
python_class('src/pactown/events.py', 'EventStore').
python_method('EventStore', '__init__', 1, 1, 4).
python_method('EventStore', '_load_from_file', 0, 3, 5).
python_method('EventStore', '_save_to_file', 0, 3, 4).
python_method('EventStore', 'append', 1, 2, 4).
python_method('EventStore', '_notify_subscribers', 1, 4, 4).
python_method('EventStore', 'subscribe', 2, 1, 2).
python_method('EventStore', 'subscribe_all', 1, 1, 2).
python_method('EventStore', 'get_events', 7, 19, 0).
python_method('EventStore', 'get_aggregate_history', 1, 3, 1).
python_method('EventStore', 'count', 1, 4, 1).
python_method('EventStore', 'get_current_sequence', 0, 1, 0).
python_method('EventStore', 'clear', 0, 3, 3).
python_class('src/pactown/events.py', 'Aggregate').
python_method('Aggregate', '__init__', 2, 1, 0).
python_method('Aggregate', 'apply_event', 1, 7, 0).
python_method('Aggregate', 'load_from_history', 1, 2, 1).
python_method('Aggregate', 'raise_event', 3, 2, 3).
python_method('Aggregate', 'get_pending_events', 0, 1, 1).
python_method('Aggregate', 'clear_pending_events', 0, 1, 1).
python_method('Aggregate', 'load', 3, 1, 3).
python_class('src/pactown/events.py', 'ServiceAggregate').
python_method('ServiceAggregate', '__init__', 1, 1, 2).
python_method('ServiceAggregate', 'apply_event', 1, 7, 1).
python_method('ServiceAggregate', 'to_dict', 0, 3, 1).
python_class('src/pactown/events.py', 'ServiceCommands').
python_method('ServiceCommands', '__init__', 1, 1, 0).
python_method('ServiceCommands', 'create_service', 4, 1, 2).
python_method('ServiceCommands', 'start_service', 4, 1, 2).
python_method('ServiceCommands', 'stop_service', 2, 1, 2).
python_method('ServiceCommands', 'record_error', 4, 2, 2).
python_method('ServiceCommands', 'record_health_check', 4, 1, 2).
python_method('ServiceCommands', 'delete_service', 2, 2, 2).
python_class('src/pactown/events.py', 'ProjectCommands').
python_method('ProjectCommands', '__init__', 1, 1, 0).
python_method('ProjectCommands', 'create_project', 3, 1, 2).
python_method('ProjectCommands', 'update_project', 3, 2, 2).
python_method('ProjectCommands', 'delete_project', 2, 2, 2).
python_class('src/pactown/events.py', 'SecurityCommands').
python_method('SecurityCommands', '__init__', 1, 1, 0).
python_method('SecurityCommands', 'record_security_check', 5, 3, 2).
python_method('SecurityCommands', 'record_rate_limit', 3, 1, 2).
python_method('SecurityCommands', 'record_anomaly', 4, 2, 2).
python_class('src/pactown/events.py', 'ServiceQueries').
python_method('ServiceQueries', '__init__', 1, 1, 0).
python_method('ServiceQueries', 'get_service_history', 1, 2, 2).
python_method('ServiceQueries', 'get_recent_starts', 1, 2, 2).
python_method('ServiceQueries', 'get_recent_errors', 1, 2, 2).
python_method('ServiceQueries', 'get_recent_health_checks', 2, 3, 2).
python_method('ServiceQueries', 'get_stats', 0, 1, 1).
python_method('ServiceQueries', 'get_service_state', 1, 1, 2).
python_method('ServiceQueries', 'get_user_services', 1, 4, 3).
python_class('src/pactown/events.py', 'ProjectQueries').
python_method('ProjectQueries', '__init__', 1, 1, 0).
python_method('ProjectQueries', 'get_project_history', 1, 2, 2).
python_method('ProjectQueries', 'get_recent_projects', 2, 5, 3).
python_method('ProjectQueries', 'get_stats', 0, 1, 1).
python_class('src/pactown/events.py', 'SecurityQueries').
python_method('SecurityQueries', '__init__', 1, 1, 0).
python_method('SecurityQueries', 'get_recent_security_failures', 1, 2, 2).
python_method('SecurityQueries', 'get_user_security_history', 2, 2, 2).
python_method('SecurityQueries', 'get_rate_limit_hits', 2, 2, 2).
python_method('SecurityQueries', 'get_anomalies', 2, 5, 3).
python_method('SecurityQueries', 'get_stats', 0, 1, 1).
python_class('src/pactown/events.py', 'Projection').
python_method('Projection', '__init__', 1, 1, 0).
python_method('Projection', 'apply', 1, 11, 0).
python_method('Projection', 'rebuild', 0, 2, 2).
python_method('Projection', 'catch_up', 0, 2, 2).
python_class('src/pactown/events.py', 'ServiceStatusProjection').
python_method('ServiceStatusProjection', '__init__', 1, 1, 2).
python_method('ServiceStatusProjection', 'apply', 1, 11, 3).
python_method('ServiceStatusProjection', 'get_all', 0, 1, 2).
python_method('ServiceStatusProjection', 'get_running', 0, 3, 2).
python_method('ServiceStatusProjection', 'get_by_user', 1, 3, 2).
python_method('ServiceStatusProjection', 'get', 1, 1, 1).
python_class('src/pactown/fast_start.py', 'CachedVenv').
python_method('CachedVenv', 'is_valid', 0, 1, 1).
python_class('src/pactown/fast_start.py', 'PrewarmedSandbox').
python_class('src/pactown/fast_start.py', 'FastStartResult').
python_class('src/pactown/fast_start.py', 'DependencyCache').
python_method('DependencyCache', '__init__', 3, 1, 3).
python_method('DependencyCache', '_load_existing', 0, 5, 10).
python_method('DependencyCache', '_hash_deps', 1, 1, 7).
python_method('DependencyCache', 'get_cached_venv', 1, 5, 6).
python_method('DependencyCache', 'invalidate', 1, 3, 4).
python_method('DependencyCache', 'save_existing_venv', 3, 5, 18).
python_method('DependencyCache', 'create_and_cache', 3, 6, 20).
python_method('DependencyCache', '_cleanup_old', 0, 8, 9).
python_method('DependencyCache', 'get_stats', 0, 2, 3).
python_class('src/pactown/fast_start.py', 'SandboxPool').
python_method('SandboxPool', '__init__', 3, 1, 2).
python_method('SandboxPool', '_hash_deps', 1, 1, 1).
python_method('SandboxPool', 'warm_pool', 1, 4, 5).
python_method('SandboxPool', 'get_prewarmed', 1, 4, 1).
python_method('SandboxPool', 'release', 1, 1, 0).
python_class('src/pactown/fast_start.py', 'FastServiceStarter').
python_method('FastServiceStarter', '__init__', 4, 1, 4).
python_method('FastServiceStarter', 'fast_create_sandbox', 4, 20, 29).
python_method('FastServiceStarter', '_write_files_parallel', 2, 1, 6).
python_method('FastServiceStarter', '_install_deps_direct', 3, 2, 4).
python_method('FastServiceStarter', 'get_cache_stats', 0, 2, 1).
python_class('src/pactown/fast_start.py', 'ParallelServiceRunner').
python_method('ParallelServiceRunner', '__init__', 2, 1, 1).
python_method('ParallelServiceRunner', 'run_parallel', 2, 2, 5).
python_class('src/pactown/iac.py', 'SandboxIacOptions').
python_method('SandboxIacOptions', 'from_env', 2, 5, 6).
python_class('src/pactown/llm.py', 'PactownLLMError').
python_class('src/pactown/llm.py', 'LLMNotAvailableError').
python_class('src/pactown/llm.py', 'PactownLLM').
python_method('PactownLLM', '__init__', 1, 4, 3).
python_method('PactownLLM', 'get_instance', 2, 2, 1).
python_method('PactownLLM', 'set_instance', 2, 1, 0).
python_method('PactownLLM', 'initialize', 0, 8, 10).
python_method('PactownLLM', 'is_available', 0, 2, 1).
python_method('PactownLLM', 'generate', 4, 3, 3).
python_method('PactownLLM', 'generate_with_rotation', 4, 3, 5).
python_method('PactownLLM', 'generate_with_fallback', 4, 2, 2).
python_method('PactownLLM', 'get_status', 0, 6, 6).
python_method('PactownLLM', 'get_provider_health', 1, 3, 4).
python_method('PactownLLM', 'set_provider_priority', 2, 2, 2).
python_method('PactownLLM', 'reset_provider', 1, 2, 2).
python_method('PactownLLM', 'get_rotation_queue', 0, 1, 1).
python_method('PactownLLM', 'on_rate_limit', 1, 1, 0).
python_method('PactownLLM', 'on_rotation', 1, 1, 0).
python_method('PactownLLM', 'on_provider_unavailable', 1, 1, 0).
python_class('src/pactown/network.py', 'ServiceEndpoint').
python_method('ServiceEndpoint', 'url', 0, 1, 0).
python_method('ServiceEndpoint', 'health_url', 0, 2, 0).
python_class('src/pactown/network.py', 'PortAllocator').
python_method('PortAllocator', '__init__', 2, 2, 2).
python_method('PortAllocator', 'is_port_free', 1, 3, 3).
python_method('PortAllocator', 'allocate', 1, 6, 4).
python_method('PortAllocator', 'release', 1, 1, 1).
python_method('PortAllocator', 'release_all', 0, 1, 1).
python_class('src/pactown/network.py', 'ServiceRegistry').
python_method('ServiceRegistry', '__init__', 2, 2, 4).
python_method('ServiceRegistry', '_load', 0, 4, 6).
python_method('ServiceRegistry', '_save', 0, 2, 3).
python_method('ServiceRegistry', 'register', 3, 3, 5).
python_method('ServiceRegistry', 'unregister', 1, 2, 2).
python_method('ServiceRegistry', 'get', 1, 1, 1).
python_method('ServiceRegistry', 'get_url', 1, 2, 1).
python_method('ServiceRegistry', 'list_services', 0, 1, 2).
python_method('ServiceRegistry', 'get_environment', 2, 4, 3).
python_method('ServiceRegistry', 'clear', 0, 2, 4).
python_class('src/pactown/node_cache.py', 'CachedNodeModules').
python_method('CachedNodeModules', 'is_valid', 0, 2, 3).
python_class('src/pactown/node_cache.py', 'NodeModulesCache').
python_method('NodeModulesCache', '__init__', 3, 1, 3).
python_method('NodeModulesCache', 'get', 1, 4, 5).
python_method('NodeModulesCache', 'restore', 3, 4, 5).
python_method('NodeModulesCache', 'save', 3, 5, 11).
python_method('NodeModulesCache', 'invalidate', 1, 2, 3).
python_method('NodeModulesCache', 'get_stats', 0, 2, 5).
python_method('NodeModulesCache', '_hash_pkg', 1, 2, 7).
python_method('NodeModulesCache', '_load_existing', 0, 7, 8).
python_method('NodeModulesCache', '_evict', 0, 7, 6).
python_class('src/pactown/orchestrator.py', 'ServiceHealth').
python_class('src/pactown/orchestrator.py', 'Orchestrator').
python_method('Orchestrator', '__init__', 4, 2, 5).
python_method('Orchestrator', 'from_file', 4, 1, 3).
python_method('Orchestrator', '_get_readme_path', 1, 2, 2).
python_method('Orchestrator', 'validate', 0, 5, 5).
python_method('Orchestrator', 'start_service', 1, 7, 8).
python_method('Orchestrator', 'start_all', 3, 2, 2).
python_method('Orchestrator', '_start_all_sequential', 1, 7, 8).
python_method('Orchestrator', '_start_all_parallel', 2, 19, 20).
python_method('Orchestrator', '_start_service_with_health', 2, 3, 3).
python_method('Orchestrator', 'stop_service', 1, 4, 2).
python_method('Orchestrator', 'stop_all', 0, 4, 6).
python_method('Orchestrator', 'restart_service', 1, 1, 3).
python_method('Orchestrator', 'check_health', 1, 7, 4).
python_method('Orchestrator', '_wait_for_health', 2, 7, 4).
python_method('Orchestrator', 'print_status', 0, 9, 8).
python_method('Orchestrator', 'print_graph', 0, 1, 3).
python_method('Orchestrator', 'get_logs', 2, 4, 1).
python_class('src/pactown/parallel.py', 'TaskResult').
python_class('src/pactown/parallel.py', 'ParallelSandboxBuilder').
python_method('ParallelSandboxBuilder', '__init__', 1, 1, 1).
python_method('ParallelSandboxBuilder', 'build_sandboxes', 2, 2, 2).
python_class('src/pactown/platform.py', 'DomainConfig').
python_method('DomainConfig', '_normalize_domain', 2, 2, 2).
python_method('DomainConfig', '_normalize_separator', 2, 1, 2).
python_class('src/pactown/platform.py', 'ProjectHostParts').
python_class('src/pactown/registry/client.py', 'RegistryClient').
python_method('RegistryClient', '__init__', 2, 1, 2).
python_method('RegistryClient', '__enter__', 0, 1, 0).
python_method('RegistryClient', '__exit__', 0, 1, 1).
python_method('RegistryClient', 'close', 0, 1, 1).
python_method('RegistryClient', 'health', 0, 2, 1).
python_method('RegistryClient', 'list_artifacts', 2, 3, 3).
python_method('RegistryClient', 'get_artifact', 2, 3, 3).
python_method('RegistryClient', 'get_version', 3, 3, 3).
python_method('RegistryClient', 'get_readme', 3, 3, 3).
python_method('RegistryClient', 'publish', 8, 4, 7).
python_method('RegistryClient', 'pull', 4, 3, 4).
python_method('RegistryClient', 'delete', 2, 2, 1).
python_method('RegistryClient', 'list_namespaces', 0, 2, 3).
python_class('src/pactown/registry/client.py', 'AsyncRegistryClient').
python_method('AsyncRegistryClient', '__init__', 2, 1, 2).
python_method('AsyncRegistryClient', '__aenter__', 0, 1, 0).
python_method('AsyncRegistryClient', '__aexit__', 0, 1, 1).
python_method('AsyncRegistryClient', 'close', 0, 1, 1).
python_method('AsyncRegistryClient', 'health', 0, 2, 1).
python_method('AsyncRegistryClient', 'list_artifacts', 2, 3, 3).
python_method('AsyncRegistryClient', 'get_readme', 3, 3, 3).
python_method('AsyncRegistryClient', 'publish', 7, 4, 4).
python_class('src/pactown/registry/models.py', 'ArtifactVersion').
python_method('ArtifactVersion', 'to_dict', 0, 2, 1).
python_method('ArtifactVersion', 'from_dict', 2, 2, 3).
python_class('src/pactown/registry/models.py', 'Artifact').
python_method('Artifact', 'full_name', 0, 1, 0).
python_method('Artifact', 'add_version', 1, 1, 1).
python_method('Artifact', 'get_version', 1, 3, 1).
python_method('Artifact', 'to_dict', 0, 2, 3).
python_method('Artifact', 'from_dict', 2, 2, 5).
python_class('src/pactown/registry/models.py', 'RegistryStorage').
python_method('RegistryStorage', '__init__', 1, 1, 3).
python_method('RegistryStorage', '_load', 0, 3, 6).
python_method('RegistryStorage', '_save', 0, 2, 6).
python_method('RegistryStorage', 'get', 2, 1, 1).
python_method('RegistryStorage', 'list', 1, 4, 2).
python_method('RegistryStorage', 'save_artifact', 1, 1, 1).
python_method('RegistryStorage', 'delete', 2, 2, 1).
python_method('RegistryStorage', 'search', 1, 6, 4).
python_class('src/pactown/registry/server.py', 'PublishRequest').
python_class('src/pactown/registry/server.py', 'PublishResponse').
python_class('src/pactown/registry/server.py', 'ArtifactInfo').
python_class('src/pactown/registry/server.py', 'VersionInfo').
python_class('src/pactown/resolver.py', 'ResolvedDependency').
python_class('src/pactown/resolver.py', 'DependencyResolver').
python_method('DependencyResolver', '__init__', 1, 1, 1).
python_method('DependencyResolver', '_build_graph', 0, 4, 2).
python_method('DependencyResolver', 'get_startup_order', 0, 9, 8).
python_method('DependencyResolver', 'get_shutdown_order', 0, 1, 3).
python_method('DependencyResolver', 'resolve_service_deps', 1, 8, 5).
python_method('DependencyResolver', 'get_environment', 1, 4, 4).
python_method('DependencyResolver', 'validate', 0, 6, 4).
python_method('DependencyResolver', 'print_graph', 0, 6, 5).
python_class('src/pactown/runner_api.py', 'UserProfileRequest').
python_class('src/pactown/runner_api.py', 'RunRequest').
python_class('src/pactown/runner_api.py', 'StopRequest').
python_class('src/pactown/runner_api.py', 'ValidateRequest').
python_class('src/pactown/runner_api.py', 'SandboxPrepareRequest').
python_class('src/pactown/runner_api.py', 'SandboxFileWriteRequest').
python_class('src/pactown/runner_api.py', 'RunnerApiSettings').
python_method('RunnerApiSettings', '__init__', 0, 1, 5).
python_class('src/pactown/runner_api.py', 'RunnerService').
python_method('RunnerService', '__init__', 0, 1, 3).
python_method('RunnerService', '_resolve_service_id', 3, 3, 4).
python_method('RunnerService', 'validate', 1, 1, 1).
python_method('RunnerService', '_sandbox_path_for', 1, 1, 2).
python_method('RunnerService', 'list_sandbox_files', 1, 5, 12).
python_method('RunnerService', 'read_sandbox_file', 3, 5, 8).
python_method('RunnerService', 'write_sandbox_file', 3, 1, 5).
python_method('RunnerService', 'delete_sandbox_file', 2, 4, 7).
python_method('RunnerService', 'prepare_sandbox', 3, 4, 10).
python_method('RunnerService', 'run', 0, 14, 12).
python_class('src/pactown/runner_types.py', 'ErrorCategory').
python_class('src/pactown/runner_types.py', 'DiagnosticInfo').
python_method('DiagnosticInfo', 'collect', 2, 6, 7).
python_class('src/pactown/runner_types.py', 'AutoFixSuggestion').
python_class('src/pactown/runner_types.py', 'RunResult').
python_method('RunResult', 'to_dict', 0, 4, 1).
python_class('src/pactown/runner_types.py', 'EndpointTestResult').
python_class('src/pactown/runner_types.py', 'ValidationResult').
python_class('src/pactown/sandbox_manager.py', 'ServiceProcess').
python_method('ServiceProcess', 'is_running', 0, 5, 4).
python_class('src/pactown/sandbox_manager.py', 'SandboxManager').
python_method('SandboxManager', '_is_node_lang', 1, 2, 2).
python_method('SandboxManager', '_infer_node_project', 0, 22, 8).
python_method('SandboxManager', '_ensure_package_json', 0, 12, 10).
python_method('SandboxManager', '_install_node_deps', 0, 34, 35).
python_method('SandboxManager', '__init__', 1, 1, 4).
python_method('SandboxManager', 'get_sandbox_path', 1, 1, 0).
python_method('SandboxManager', 'create_sandbox', 5, 67, 63).
python_method('SandboxManager', 'build_service', 2, 40, 39).
python_method('SandboxManager', 'start_service', 7, 53, 61).
python_method('SandboxManager', 'stop_service', 2, 10, 8).
python_method('SandboxManager', 'stop_all', 1, 2, 3).
python_method('SandboxManager', 'get_status', 1, 2, 2).
python_method('SandboxManager', 'get_all_status', 0, 3, 1).
python_method('SandboxManager', 'clean_sandbox', 1, 2, 3).
python_method('SandboxManager', 'clean_all', 0, 2, 3).
python_method('SandboxManager', 'create_sandboxes_parallel', 3, 8, 12).
python_method('SandboxManager', 'start_services_parallel', 3, 6, 9).
python_class('src/pactown/security.py', 'AnomalyType').
python_class('src/pactown/security.py', 'UserTier').
python_class('src/pactown/security.py', 'UserProfile').
python_method('UserProfile', 'from_tier', 3, 1, 2).
python_method('UserProfile', 'to_dict', 0, 2, 0).
python_method('UserProfile', 'from_dict', 2, 1, 3).
python_class('src/pactown/security.py', 'AnomalyEvent').
python_method('AnomalyEvent', 'to_dict', 0, 2, 1).
python_method('AnomalyEvent', 'to_log_line', 0, 1, 1).
python_class('src/pactown/security.py', 'AnomalyLogger').
python_method('AnomalyLogger', '__init__', 3, 1, 4).
python_method('AnomalyLogger', 'log', 6, 6, 13).
python_method('AnomalyLogger', 'get_recent', 1, 1, 0).
python_method('AnomalyLogger', 'get_by_user', 2, 3, 0).
python_method('AnomalyLogger', 'get_by_type', 2, 3, 0).
python_class('src/pactown/security.py', 'RateLimiter').
python_method('RateLimiter', '__init__', 2, 1, 1).
python_method('RateLimiter', '_get_bucket', 1, 2, 2).
python_method('RateLimiter', 'check', 1, 1, 1).
python_method('RateLimiter', 'consume', 1, 2, 1).
python_method('RateLimiter', 'get_wait_time', 1, 2, 1).
python_class('src/pactown/security.py', 'ResourceMonitor').
python_method('ResourceMonitor', '__init__', 3, 1, 1).
python_method('ResourceMonitor', '_get_cpu_percent', 0, 3, 4).
python_method('ResourceMonitor', '_get_memory_percent', 0, 4, 6).
python_method('ResourceMonitor', 'check_overload', 0, 3, 3).
python_method('ResourceMonitor', 'get_throttle_delay', 0, 2, 4).
python_class('src/pactown/security.py', 'SecurityCheckResult').
python_method('SecurityCheckResult', 'to_dict', 0, 2, 1).
python_class('src/pactown/security.py', 'SecurityPolicy').
python_method('SecurityPolicy', '__init__', 5, 1, 4).
python_method('SecurityPolicy', 'set_user_profile', 1, 1, 0).
python_method('SecurityPolicy', 'get_user_profile', 1, 2, 1).
python_method('SecurityPolicy', 'register_service', 2, 6, 2).
python_method('SecurityPolicy', 'unregister_service', 2, 3, 1).
python_method('SecurityPolicy', 'get_user_service_count', 1, 1, 2).
python_method('SecurityPolicy', 'get_services_started_last_hour', 1, 3, 3).
python_method('SecurityPolicy', 'check_can_start_service', 3, 14, 13).
python_method('SecurityPolicy', 'get_anomaly_summary', 1, 7, 9).
python_class('src/pactown/service_runner.py', 'ServiceRunner').
python_method('ServiceRunner', '__init__', 6, 5, 9).
python_method('ServiceRunner', 'validate_content', 1, 25, 14).
python_method('ServiceRunner', '_extract_required_env_vars', 1, 19, 15).
python_method('ServiceRunner', '_missing_required_env_vars', 2, 5, 6).
python_method('ServiceRunner', '_prune_stale_user_services', 2, 14, 8).
python_method('ServiceRunner', 'run_from_content', 10, 37, 38).
python_method('ServiceRunner', '_generate_suggestions', 3, 18, 4).
python_method('ServiceRunner', '_wait_for_health', 5, 30, 14).
python_method('ServiceRunner', 'stop', 1, 6, 7).
python_method('ServiceRunner', 'get_status', 1, 3, 2).
python_method('ServiceRunner', 'list_services', 0, 4, 4).
python_method('ServiceRunner', 'test_endpoints', 3, 8, 7).
python_method('ServiceRunner', 'stop_all', 0, 2, 3).
python_method('ServiceRunner', 'fast_run', 8, 36, 44).
python_method('ServiceRunner', '_quick_health_check', 4, 12, 8).
python_method('ServiceRunner', 'get_cache_stats', 0, 2, 1).
python_class('src/pactown/targets.py', 'TargetPlatform').
python_class('src/pactown/targets.py', 'DesktopFramework').
python_class('src/pactown/targets.py', 'MobileFramework').
python_class('src/pactown/targets.py', 'WebFramework').
python_class('src/pactown/targets.py', 'FrameworkMeta').
python_class('src/pactown/targets.py', 'TargetConfig').
python_method('TargetConfig', 'from_yaml_body', 2, 3, 3).
python_method('TargetConfig', 'from_dict', 2, 10, 11).
python_method('TargetConfig', 'framework_meta', 0, 2, 1).
python_method('TargetConfig', 'is_web', 0, 1, 0).
python_method('TargetConfig', 'is_desktop', 0, 1, 0).
python_method('TargetConfig', 'is_mobile', 0, 1, 0).
python_method('TargetConfig', 'is_buildable', 0, 1, 0).
python_method('TargetConfig', 'needs_port', 0, 1, 0).
python_method('TargetConfig', 'effective_build_targets', 0, 4, 0).
python_class('src/pactown/user_isolation.py', 'IsolatedUser').
python_method('IsolatedUser', 'to_dict', 0, 1, 1).
python_class('src/pactown/user_isolation.py', 'UserIsolationManager').
python_method('UserIsolationManager', '__init__', 2, 2, 5).
python_method('UserIsolationManager', 'can_isolate', 0, 7, 4).
python_method('UserIsolationManager', '_load_existing_users', 0, 6, 6).
python_method('UserIsolationManager', '_generate_username', 1, 1, 3).
python_method('UserIsolationManager', 'get_or_create_user', 1, 15, 22).
python_method('UserIsolationManager', 'get_user', 1, 1, 1).
python_method('UserIsolationManager', 'get_sandbox_path', 2, 2, 4).
python_method('UserIsolationManager', 'run_as_user', 4, 3, 9).
python_method('UserIsolationManager', 'list_users', 0, 1, 2).
python_method('UserIsolationManager', 'get_user_stats', 1, 5, 10).
python_method('UserIsolationManager', 'export_user_data', 2, 4, 6).
python_method('UserIsolationManager', 'import_user_data', 2, 3, 6).
python_method('UserIsolationManager', 'delete_user', 2, 7, 8).
python_class('tests/test_ansible.py', 'TestAnsibleConfig').
python_method('TestAnsibleConfig', 'test_defaults', 0, 9, 1).
python_method('TestAnsibleConfig', 'test_for_local', 0, 4, 1).
python_method('TestAnsibleConfig', 'test_for_remote_single_host', 0, 6, 1).
python_method('TestAnsibleConfig', 'test_for_remote_multiple_hosts', 0, 3, 1).
python_method('TestAnsibleConfig', 'test_custom_extra_vars', 0, 3, 1).
python_method('TestAnsibleConfig', 'test_galaxy_requirements', 0, 2, 1).
python_method('TestAnsibleConfig', 'test_roles_path', 0, 2, 1).
python_method('TestAnsibleConfig', 'test_verbosity_levels', 0, 3, 1).
python_class('tests/test_ansible.py', 'TestGenerateInventory').
python_method('TestGenerateInventory', 'test_single_remote_host', 0, 3, 1).
python_method('TestGenerateInventory', 'test_localhost_gets_local_connection', 0, 2, 1).
python_method('TestGenerateInventory', 'test_127_0_0_1_gets_local_connection', 0, 2, 1).
python_method('TestGenerateInventory', 'test_multiple_hosts', 0, 2, 3).
python_method('TestGenerateInventory', 'test_custom_group_name', 0, 2, 1).
python_method('TestGenerateInventory', 'test_ssh_key_path', 0, 2, 1).
python_method('TestGenerateInventory', 'test_no_ssh_key', 0, 2, 1).
python_method('TestGenerateInventory', 'test_local_connection_skips_ansible_connection_var', 0, 2, 1).
python_method('TestGenerateInventory', 'test_ssh_connection_sets_ansible_connection_var', 0, 2, 1).
python_method('TestGenerateInventory', 'test_yaml_serialisable', 0, 2, 3).
python_class('tests/test_ansible.py', 'TestGenerateDeployPlaybook').
python_method('TestGenerateDeployPlaybook', 'test_basic_structure', 0, 5, 5).
python_method('TestGenerateDeployPlaybook', 'test_pull_task', 0, 4, 3).
python_method('TestGenerateDeployPlaybook', 'test_network_task', 0, 3, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_task_port_mapping', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_task_no_port_when_not_exposed', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_env', 0, 3, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_memory_limit', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_read_only_fs', 0, 3, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_no_new_privileges', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_drop_capabilities', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_healthcheck_tasks_present', 0, 5, 4).
python_method('TestGenerateDeployPlaybook', 'test_no_healthcheck_when_none', 0, 2, 4).
python_method('TestGenerateDeployPlaybook', 'test_container_healthcheck_params', 0, 6, 3).
python_method('TestGenerateDeployPlaybook', 'test_become_settings', 0, 3, 3).
python_method('TestGenerateDeployPlaybook', 'test_no_become', 0, 3, 3).
python_method('TestGenerateDeployPlaybook', 'test_container_name_includes_namespace', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_restart_policy', 0, 2, 3).
python_method('TestGenerateDeployPlaybook', 'test_yaml_serialisable', 0, 2, 5).
python_class('tests/test_ansible.py', 'TestGenerateTeardownPlaybook').
python_method('TestGenerateTeardownPlaybook', 'test_structure', 0, 5, 3).
python_method('TestGenerateTeardownPlaybook', 'test_container_name', 0, 3, 2).
python_method('TestGenerateTeardownPlaybook', 'test_stop_tag', 0, 2, 2).
python_class('tests/test_ansible.py', 'TestGenerateBuildPlaybook').
python_method('TestGenerateBuildPlaybook', 'test_basic', 0, 6, 2).
python_method('TestGenerateBuildPlaybook', 'test_with_build_args', 0, 3, 1).
python_method('TestGenerateBuildPlaybook', 'test_no_build_args', 0, 2, 1).
python_method('TestGenerateBuildPlaybook', 'test_build_tag', 0, 2, 1).
python_class('tests/test_ansible.py', 'TestAnsibleBackendDryRun').
python_method('TestAnsibleBackendDryRun', '_backend', 1, 1, 3).
python_method('TestAnsibleBackendDryRun', 'test_runtime_type', 1, 2, 1).
python_method('TestAnsibleBackendDryRun', 'test_deploy_writes_files', 1, 8, 5).
python_method('TestAnsibleBackendDryRun', 'test_deploy_endpoint', 1, 2, 2).
python_method('TestAnsibleBackendDryRun', 'test_deploy_no_endpoint_when_ports_not_exposed', 1, 2, 3).
python_method('TestAnsibleBackendDryRun', 'test_stop_writes_teardown', 1, 3, 3).
python_method('TestAnsibleBackendDryRun', 'test_build_image_writes_playbook', 1, 5, 4).
python_method('TestAnsibleBackendDryRun', 'test_build_image_default_tag', 1, 2, 4).
python_method('TestAnsibleBackendDryRun', 'test_push_image_writes_playbook', 1, 4, 3).
python_method('TestAnsibleBackendDryRun', 'test_push_image_no_registry', 1, 2, 2).
python_method('TestAnsibleBackendDryRun', 'test_logs_dry_run', 1, 3, 2).
python_method('TestAnsibleBackendDryRun', 'test_status_dry_run', 1, 3, 2).
python_method('TestAnsibleBackendDryRun', 'test_write_all', 1, 7, 6).
python_method('TestAnsibleBackendDryRun', 'test_write_all_no_health_check', 1, 2, 5).
python_class('tests/test_ansible.py', 'TestAnsibleBackendAvailability').
python_method('TestAnsibleBackendAvailability', 'test_available_when_ansible_installed', 2, 2, 5).
python_method('TestAnsibleBackendAvailability', 'test_not_available_when_not_installed', 2, 2, 4).
python_method('TestAnsibleBackendAvailability', 'test_not_available_on_timeout', 2, 2, 5).
python_class('tests/test_ansible.py', 'TestAnsibleBackendRun').
python_method('TestAnsibleBackendRun', '_backend', 1, 1, 3).
python_method('TestAnsibleBackendRun', 'test_deploy_runs_ansible_playbook', 2, 4, 4).
python_method('TestAnsibleBackendRun', 'test_deploy_failure', 2, 3, 4).
python_method('TestAnsibleBackendRun', 'test_deploy_timeout', 2, 3, 4).
python_method('TestAnsibleBackendRun', 'test_deploy_ansible_not_found', 2, 3, 3).
python_method('TestAnsibleBackendRun', 'test_stop_runs_ansible_playbook', 2, 2, 4).
python_method('TestAnsibleBackendRun', 'test_verbosity_flag', 2, 2, 6).
python_method('TestAnsibleBackendRun', 'test_extra_vars_passed', 2, 3, 7).
python_method('TestAnsibleBackendRun', 'test_build_image_non_dry_run', 2, 2, 5).
python_method('TestAnsibleBackendRun', 'test_push_image_non_dry_run', 2, 2, 4).
python_class('tests/test_ansible.py', 'TestAnsibleBackendLogsStatus').
python_method('TestAnsibleBackendLogsStatus', 'test_logs_calls_docker', 2, 4, 5).
python_method('TestAnsibleBackendLogsStatus', 'test_status_running', 2, 3, 6).
python_method('TestAnsibleBackendLogsStatus', 'test_status_not_found', 2, 2, 5).
python_method('TestAnsibleBackendLogsStatus', 'test_logs_docker_not_available', 2, 2, 4).
python_class('tests/test_ansible.py', 'TestPlaybookYamlContent').
python_method('TestPlaybookYamlContent', 'test_deploy_playbook_roundtrips', 1, 2, 6).
python_method('TestPlaybookYamlContent', 'test_inventory_has_all_hosts', 1, 2, 8).
python_method('TestPlaybookYamlContent', 'test_teardown_playbook_content', 1, 3, 5).
python_class('tests/test_ansible.py', 'TestIntegrationWithDeploymentConfig').
python_method('TestIntegrationWithDeploymentConfig', 'test_production_config', 1, 4, 5).
python_method('TestIntegrationWithDeploymentConfig', 'test_development_config', 1, 3, 5).
python_class('tests/test_ansible.py', 'TestAnsibleDesktopIntegration').
python_method('TestAnsibleDesktopIntegration', 'test_electron_build_and_deploy_playbook', 1, 7, 10).
python_method('TestAnsibleDesktopIntegration', 'test_tauri_build_scaffold_with_ansible_deployment', 1, 6, 11).
python_method('TestAnsibleDesktopIntegration', 'test_pyinstaller_scaffold_and_ansible_build_playbook', 1, 6, 12).
python_method('TestAnsibleDesktopIntegration', 'test_pyqt_scaffold_with_icon_and_ansible', 1, 4, 9).
python_method('TestAnsibleDesktopIntegration', 'test_electron_multi_platform_build_with_ansible_matrix', 1, 7, 9).
python_class('tests/test_ansible.py', 'TestAnsibleMobileIntegration').
python_method('TestAnsibleMobileIntegration', 'test_capacitor_scaffold_and_ansible_deployment', 1, 9, 11).
python_method('TestAnsibleMobileIntegration', 'test_react_native_scaffold_with_ansible', 1, 6, 11).
python_method('TestAnsibleMobileIntegration', 'test_flutter_scaffold_android_ios_with_ansible', 1, 4, 9).
python_method('TestAnsibleMobileIntegration', 'test_kivy_buildozer_scaffold_with_ansible', 1, 6, 9).
python_method('TestAnsibleMobileIntegration', 'test_capacitor_webdir_detection_with_ansible', 1, 4, 9).
python_class('tests/test_ansible.py', 'TestE2EBuildAndAnsibleDeploy').
python_method('TestE2EBuildAndAnsibleDeploy', 'test_desktop_electron_full_workflow', 1, 7, 10).
python_method('TestE2EBuildAndAnsibleDeploy', 'test_mobile_capacitor_full_workflow', 1, 5, 11).
python_method('TestE2EBuildAndAnsibleDeploy', 'test_multi_service_ansible_deployment', 1, 4, 14).
python_class('tests/test_ansible.py', 'TestDesktopArtifactGeneration').
python_method('TestDesktopArtifactGeneration', 'test_electron_linux_appimage_artifact', 1, 4, 11).
python_method('TestDesktopArtifactGeneration', 'test_electron_windows_exe_artifact', 1, 4, 9).
python_method('TestDesktopArtifactGeneration', 'test_electron_macos_dmg_artifact', 1, 4, 9).
python_method('TestDesktopArtifactGeneration', 'test_electron_snap_artifact', 1, 2, 7).
python_method('TestDesktopArtifactGeneration', 'test_electron_linux_launcher_artifacts', 1, 5, 5).
python_method('TestDesktopArtifactGeneration', 'test_tauri_linux_appimage_artifact', 1, 3, 7).
python_method('TestDesktopArtifactGeneration', 'test_tauri_deb_artifact', 1, 2, 6).
python_method('TestDesktopArtifactGeneration', 'test_pyinstaller_linux_binary_artifact', 1, 3, 6).
python_method('TestDesktopArtifactGeneration', 'test_pyinstaller_windows_exe_artifact', 1, 2, 4).
python_method('TestDesktopArtifactGeneration', 'test_pyqt_multi_os_artifacts', 1, 2, 5).
python_class('tests/test_ansible.py', 'TestMobileArtifactGeneration').
python_method('TestMobileArtifactGeneration', 'test_capacitor_android_apk_artifact', 1, 4, 10).
python_method('TestMobileArtifactGeneration', 'test_capacitor_android_release_apk_artifact', 1, 2, 6).
python_method('TestMobileArtifactGeneration', 'test_capacitor_ios_ipa_artifact', 1, 2, 6).
python_method('TestMobileArtifactGeneration', 'test_capacitor_dual_platform_artifacts', 1, 7, 9).
python_method('TestMobileArtifactGeneration', 'test_react_native_android_apk_artifact', 1, 3, 6).
python_method('TestMobileArtifactGeneration', 'test_react_native_ios_ipa_artifact', 1, 2, 5).
python_method('TestMobileArtifactGeneration', 'test_flutter_android_apk_artifact', 1, 3, 5).
python_method('TestMobileArtifactGeneration', 'test_flutter_ios_ipa_artifact', 1, 2, 4).
python_method('TestMobileArtifactGeneration', 'test_kivy_android_apk_artifact', 1, 2, 5).
python_method('TestMobileArtifactGeneration', 'test_kivy_android_aab_artifact', 1, 2, 4).
python_class('tests/test_ansible.py', 'TestMultiPlatformArtifactsWithAnsible').
python_method('TestMultiPlatformArtifactsWithAnsible', 'test_electron_all_platforms_artifacts', 1, 9, 11).
python_method('TestMultiPlatformArtifactsWithAnsible', 'test_capacitor_android_ios_artifacts_with_ansible', 1, 4, 12).
python_method('TestMultiPlatformArtifactsWithAnsible', 'test_artifact_paths_in_ansible_playbook', 1, 5, 13).
python_method('TestMultiPlatformArtifactsWithAnsible', 'test_flutter_multi_platform_architecture_artifacts', 1, 4, 9).
python_class('tests/test_ansible.py', 'TestScaffoldConfigCorrectness').
python_method('TestScaffoldConfigCorrectness', 'test_electron_package_json_build_targets_all_os', 1, 4, 5).
python_method('TestScaffoldConfigCorrectness', 'test_electron_package_json_app_id', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_electron_package_json_default_app_id', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_electron_main_js_has_no_sandbox', 1, 3, 4).
python_method('TestScaffoldConfigCorrectness', 'test_electron_main_js_window_dimensions', 1, 3, 4).
python_method('TestScaffoldConfigCorrectness', 'test_electron_dev_deps_pinned', 1, 5, 6).
python_method('TestScaffoldConfigCorrectness', 'test_electron_moves_electron_from_deps_to_dev_deps', 1, 4, 8).
python_method('TestScaffoldConfigCorrectness', 'test_tauri_conf_bundle_identifier', 1, 3, 5).
python_method('TestScaffoldConfigCorrectness', 'test_tauri_conf_window_size', 1, 3, 5).
python_method('TestScaffoldConfigCorrectness', 'test_tauri_conf_default_window_size', 1, 3, 5).
python_method('TestScaffoldConfigCorrectness', 'test_tauri_conf_product_name', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_pyinstaller_spec_content', 1, 4, 5).
python_method('TestScaffoldConfigCorrectness', 'test_pyinstaller_spec_no_icon_by_default', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_pyqt_spec_with_icon', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_tkinter_spec_generated', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_config_json_fields', 1, 5, 6).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_scripts_in_package_json', 1, 4, 6).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_webdir_root_index', 1, 2, 6).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_webdir_build_dir', 1, 2, 6).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_webdir_www_dir', 1, 2, 6).
python_method('TestScaffoldConfigCorrectness', 'test_capacitor_plugin_version_pinning', 1, 4, 7).
python_method('TestScaffoldConfigCorrectness', 'test_react_native_app_json_display_name', 1, 3, 5).
python_method('TestScaffoldConfigCorrectness', 'test_react_native_app_json_default_display_name', 1, 2, 5).
python_method('TestScaffoldConfigCorrectness', 'test_kivy_buildozer_spec_fields', 1, 6, 4).
python_method('TestScaffoldConfigCorrectness', 'test_kivy_buildozer_spec_icon', 1, 2, 4).
python_method('TestScaffoldConfigCorrectness', 'test_kivy_buildozer_spec_no_icon', 1, 2, 4).
python_class('tests/test_ansible.py', 'TestBuildCommandGeneration').
python_method('TestBuildCommandGeneration', 'test_electron_default_build_cmd_linux', 0, 3, 1).
python_method('TestBuildCommandGeneration', 'test_electron_default_build_cmd_no_targets', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_tauri_default_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_pyinstaller_default_build_cmd', 0, 4, 1).
python_method('TestBuildCommandGeneration', 'test_pyqt_default_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_tkinter_default_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_flutter_desktop_default_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_flutter_desktop_macos_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_flutter_desktop_windows_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_unknown_framework_returns_empty', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_capacitor_android_build_cmd', 0, 3, 1).
python_method('TestBuildCommandGeneration', 'test_capacitor_ios_build_cmd', 0, 3, 1).
python_method('TestBuildCommandGeneration', 'test_react_native_android_build_cmd', 0, 3, 1).
python_method('TestBuildCommandGeneration', 'test_react_native_ios_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_flutter_android_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_flutter_ios_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_kivy_android_build_cmd', 0, 2, 1).
python_method('TestBuildCommandGeneration', 'test_kivy_ios_build_cmd', 0, 2, 1).
python_class('tests/test_ansible.py', 'TestElectronNoSandboxPatch').
python_method('TestElectronNoSandboxPatch', 'test_patch_commonjs_require', 1, 4, 4).
python_method('TestElectronNoSandboxPatch', 'test_patch_es_module_import', 1, 3, 4).
python_method('TestElectronNoSandboxPatch', 'test_patch_app_whenready_fallback', 1, 4, 4).
python_method('TestElectronNoSandboxPatch', 'test_patch_app_on_fallback', 1, 3, 4).
python_method('TestElectronNoSandboxPatch', 'test_patch_ultimate_fallback_prepend', 1, 4, 5).
python_method('TestElectronNoSandboxPatch', 'test_patch_skips_already_patched', 1, 2, 3).
python_method('TestElectronNoSandboxPatch', 'test_patch_no_main_js', 1, 2, 2).
python_class('tests/test_ansible.py', 'TestElectronBuilderFlagFiltering').
python_method('TestElectronBuilderFlagFiltering', 'test_filter_keeps_linux_flag', 0, 2, 1).
python_method('TestElectronBuilderFlagFiltering', 'test_filter_strips_mac_on_non_darwin', 0, 4, 3).
python_method('TestElectronBuilderFlagFiltering', 'test_filter_ensures_at_least_one_platform', 0, 3, 3).
python_method('TestElectronBuilderFlagFiltering', 'test_electron_builder_flags_linux_target', 0, 2, 1).
python_method('TestElectronBuilderFlagFiltering', 'test_electron_builder_flags_empty_defaults_linux', 0, 2, 1).
python_method('TestElectronBuilderFlagFiltering', 'test_electron_builder_flags_no_duplicates', 0, 2, 2).
python_class('tests/test_ansible.py', 'TestDesktopFlutterTkinterArtifacts').
python_method('TestDesktopFlutterTkinterArtifacts', 'test_flutter_desktop_linux_artifacts', 1, 4, 5).
python_method('TestDesktopFlutterTkinterArtifacts', 'test_tkinter_dist_artifacts', 1, 3, 5).
python_method('TestDesktopFlutterTkinterArtifacts', 'test_tkinter_windows_artifact', 1, 2, 4).
python_method('TestDesktopFlutterTkinterArtifacts', 'test_unknown_framework_fallback_artifacts', 1, 4, 4).
python_method('TestDesktopFlutterTkinterArtifacts', 'test_mobile_unknown_framework_fallback', 1, 3, 5).
python_class('tests/test_ansible.py', 'TestAnsibleArtifactDistribution').
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_with_electron_linux_artifacts', 1, 7, 16).
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_with_capacitor_android_artifacts', 1, 6, 14).
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_multi_os_electron_with_separate_inventories', 1, 13, 15).
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_kivy_with_buildozer_artifacts', 1, 12, 13).
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_tauri_with_multi_format_artifacts', 1, 10, 16).
python_method('TestAnsibleArtifactDistribution', 'test_ansible_deploy_react_native_dual_platform', 1, 10, 12).
python_class('tests/test_ansible.py', 'TestArtifactsInPactownSandboxRoot').
python_method('TestArtifactsInPactownSandboxRoot', 'test_sandbox_manager_uses_configured_root', 0, 4, 6).
python_method('TestArtifactsInPactownSandboxRoot', 'test_env_sandbox_root_points_to_pactown', 0, 3, 3).
python_method('TestArtifactsInPactownSandboxRoot', 'test_service_runner_default_root_from_env', 0, 3, 7).
python_method('TestArtifactsInPactownSandboxRoot', 'test_electron_artifacts_inside_sandbox_root', 0, 7, 14).
python_method('TestArtifactsInPactownSandboxRoot', 'test_capacitor_artifacts_inside_sandbox_root', 0, 4, 14).
python_method('TestArtifactsInPactownSandboxRoot', 'test_tauri_artifacts_inside_sandbox_root', 0, 3, 13).
python_method('TestArtifactsInPactownSandboxRoot', 'test_ansible_deploy_artifacts_from_sandbox_root', 0, 7, 19).
python_method('TestArtifactsInPactownSandboxRoot', 'test_dotenv_pactown_sandbox_root_is_project_local', 0, 8, 8).
python_class('tests/test_ansible.py', 'TestRealScaffoldInPactown').
python_method('TestRealScaffoldInPactown', '_root', 0, 1, 6).
python_method('TestRealScaffoldInPactown', '_svc_path', 1, 1, 1).
python_method('TestRealScaffoldInPactown', '_make_elf', 1, 1, 2).
python_method('TestRealScaffoldInPactown', '_make_pe', 1, 1, 4).
python_method('TestRealScaffoldInPactown', '_make_zip_package', 2, 4, 6).
python_method('TestRealScaffoldInPactown', '_make_apk', 3, 1, 2).
python_method('TestRealScaffoldInPactown', '_make_ipa', 3, 1, 3).
python_method('TestRealScaffoldInPactown', '_make_aab', 3, 1, 2).
python_method('TestRealScaffoldInPactown', '_make_dmg', 1, 1, 1).
python_method('TestRealScaffoldInPactown', '_make_deb', 1, 1, 1).
python_method('TestRealScaffoldInPactown', '_make_snap', 1, 1, 2).
python_method('TestRealScaffoldInPactown', '_make_msi', 1, 1, 1).
python_method('TestRealScaffoldInPactown', '_make_so', 1, 1, 2).
python_method('TestRealScaffoldInPactown', '_make_appimage', 1, 1, 2).
python_method('TestRealScaffoldInPactown', '_write_artifact', 2, 1, 2).
python_method('TestRealScaffoldInPactown', 'test_root_matches_dotenv_config', 0, 5, 7).
python_method('TestRealScaffoldInPactown', 'test_pactown_dir_exists', 0, 2, 2).
python_method('TestRealScaffoldInPactown', 'test_real_electron_scaffold_and_artifacts', 0, 15, 15).
python_method('TestRealScaffoldInPactown', 'test_real_tauri_scaffold_and_artifacts', 0, 5, 13).
python_method('TestRealScaffoldInPactown', 'test_real_pyinstaller_scaffold_and_artifacts', 0, 5, 11).
python_method('TestRealScaffoldInPactown', 'test_real_pyqt_scaffold_and_artifacts', 0, 4, 11).
python_method('TestRealScaffoldInPactown', 'test_real_tkinter_scaffold_and_artifacts', 0, 4, 11).
python_method('TestRealScaffoldInPactown', 'test_real_flutter_desktop_scaffold_and_artifacts', 0, 2, 9).
python_method('TestRealScaffoldInPactown', 'test_real_capacitor_scaffold_and_artifacts', 0, 11, 11).
python_method('TestRealScaffoldInPactown', 'test_real_react_native_scaffold_and_artifacts', 0, 4, 11).
python_method('TestRealScaffoldInPactown', 'test_real_flutter_mobile_scaffold_and_artifacts', 0, 2, 9).
python_method('TestRealScaffoldInPactown', 'test_real_kivy_scaffold_and_artifacts', 0, 10, 11).
python_method('TestRealScaffoldInPactown', 'test_real_fastapi_scaffold_and_artifacts', 0, 6, 5).
python_method('TestRealScaffoldInPactown', 'test_real_flask_scaffold_and_artifacts', 0, 4, 5).
python_method('TestRealScaffoldInPactown', 'test_real_express_scaffold_and_artifacts', 0, 3, 7).
python_method('TestRealScaffoldInPactown', 'test_real_nextjs_scaffold_and_artifacts', 0, 4, 7).
python_method('TestRealScaffoldInPactown', 'test_real_react_spa_scaffold_and_artifacts', 0, 4, 7).
python_method('TestRealScaffoldInPactown', 'test_real_vue_scaffold_and_artifacts', 0, 4, 7).
python_method('TestRealScaffoldInPactown', 'test_all_framework_dirs_present', 0, 4, 2).
python_method('TestRealScaffoldInPactown', 'test_all_artifacts_are_inside_pactown', 0, 5, 6).
python_class('tests/test_ansible.py', 'TestDockerArtifactExecution').
python_method('TestDockerArtifactExecution', '_root', 0, 1, 6).
python_method('TestDockerArtifactExecution', 'test_docker_electron_package_json', 0, 7, 4).
python_method('TestDockerArtifactExecution', 'test_docker_electron_main_js', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_electron_artifacts_exist', 0, 6, 4).
python_method('TestDockerArtifactExecution', 'test_docker_tauri_config', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_tauri_bundle_artifacts', 0, 7, 4).
python_method('TestDockerArtifactExecution', 'test_docker_pyinstaller_spec', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_pyinstaller_artifacts', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_pyqt_spec_and_artifacts', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_tkinter_spec_and_artifacts', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_flutter_desktop_bundle', 0, 6, 4).
python_method('TestDockerArtifactExecution', 'test_docker_capacitor_config', 0, 6, 4).
python_method('TestDockerArtifactExecution', 'test_docker_capacitor_apk_ipa', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_react_native_config', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_react_native_apk_ipa', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_flutter_mobile_artifacts', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_kivy_buildozer_spec', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_kivy_apk_aab', 0, 4, 4).
python_method('TestDockerArtifactExecution', 'test_docker_fastapi_syntax_and_structure', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_flask_syntax_and_structure', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_express_syntax_and_structure', 0, 5, 4).
python_method('TestDockerArtifactExecution', 'test_docker_nextjs_config_and_pages', 0, 7, 4).
python_method('TestDockerArtifactExecution', 'test_docker_react_spa_structure', 0, 7, 4).
python_method('TestDockerArtifactExecution', 'test_docker_vue_structure', 0, 7, 4).
python_method('TestDockerArtifactExecution', 'test_docker_all_frameworks_mounted', 0, 6, 4).
python_method('TestDockerArtifactExecution', 'test_docker_artifact_count', 0, 4, 6).
python_class('tests/test_ansible.py', 'TestDockerDockerfileValidation').
python_method('TestDockerDockerfileValidation', '_root', 0, 1, 5).
python_method('TestDockerDockerfileValidation', 'test_docker_fastapi_dockerfile_valid', 0, 4, 4).
python_method('TestDockerDockerfileValidation', 'test_docker_flask_dockerfile_valid', 0, 4, 4).
python_method('TestDockerDockerfileValidation', 'test_docker_express_dockerfile_valid', 0, 4, 4).
python_method('TestDockerDockerfileValidation', 'test_docker_all_web_dockerfiles_have_required_instructions', 0, 7, 3).
python_class('tests/test_ansible.py', 'TestDockerIaCValidation').
python_method('TestDockerIaCValidation', '_root', 0, 1, 5).
python_method('TestDockerIaCValidation', '_ensure_writable_dir', 1, 5, 8).
python_method('TestDockerIaCValidation', '_setup_iac_sandboxes', 0, 1, 8).
python_method('TestDockerIaCValidation', 'test_docker_iac_python_manifest_valid_yaml', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_node_manifest_valid_yaml', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_python_dockerfile_structure', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_node_dockerfile_structure', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_python_compose_valid', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_node_compose_valid', 0, 3, 2).
python_method('TestDockerIaCValidation', 'test_docker_iac_all_files_present_and_consistent', 0, 4, 4).
python_class('tests/test_ansible.py', 'TestArtifactSizeValidation').
python_method('TestArtifactSizeValidation', '_root', 0, 1, 5).
python_method('TestArtifactSizeValidation', 'test_electron_artifacts_proper_size', 0, 6, 9).
python_method('TestArtifactSizeValidation', 'test_tauri_artifacts_proper_size', 0, 6, 9).
python_method('TestArtifactSizeValidation', 'test_pyinstaller_artifacts_proper_size', 0, 6, 8).
python_method('TestArtifactSizeValidation', 'test_mobile_apk_ipa_proper_size', 0, 8, 10).
python_method('TestArtifactSizeValidation', 'test_flutter_desktop_artifacts_proper_size', 0, 6, 9).
python_method('TestArtifactSizeValidation', 'test_web_build_output_proper_size', 0, 8, 10).
python_method('TestArtifactSizeValidation', 'test_strict_no_stubs_or_undersized', 0, 12, 15).
python_method('TestArtifactSizeValidation', 'test_min_sizes_cover_all_binary_extensions', 0, 8, 10).
python_method('TestArtifactSizeValidation', 'test_artifact_size_report', 0, 9, 19).
python_class('tests/test_ansible.py', 'TestDockerArtifactSizeValidation').
python_method('TestDockerArtifactSizeValidation', '_root', 0, 1, 5).
python_method('TestDockerArtifactSizeValidation', 'test_docker_no_stub_binaries', 0, 9, 8).
python_method('TestDockerArtifactSizeValidation', 'test_docker_electron_dist_sizes_all_above_threshold', 0, 4, 4).
python_method('TestDockerArtifactSizeValidation', 'test_docker_mobile_packages_all_above_threshold', 0, 3, 4).
python_class('tests/test_ansible.py', 'TestDockerBinaryFormatVerification').
python_method('TestDockerBinaryFormatVerification', '_root', 0, 1, 5).
python_method('TestDockerBinaryFormatVerification', 'test_docker_electron_elf_headers', 0, 5, 4).
python_method('TestDockerBinaryFormatVerification', 'test_docker_pyinstaller_elf_and_pe', 0, 5, 4).
python_method('TestDockerBinaryFormatVerification', 'test_docker_flutter_desktop_elf_and_so', 0, 4, 5).
python_method('TestDockerBinaryFormatVerification', 'test_docker_tauri_bundle_formats', 0, 5, 5).
python_method('TestDockerBinaryFormatVerification', 'test_docker_mobile_zip_packages', 0, 7, 5).
python_class('tests/test_ansible.py', 'TestDockerAutomatedExecution').
python_method('TestDockerAutomatedExecution', '_root', 0, 1, 5).
python_method('TestDockerAutomatedExecution', 'test_docker_run_fastapi_syntax_check', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_fastapi_import_check', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_flask_syntax_check', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_flask_import_check', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_express_syntax_check', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_nextjs_syntax_check', 0, 5, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_react_build_output_valid', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_run_vue_build_output_valid', 0, 4, 4).
python_method('TestDockerAutomatedExecution', 'test_docker_dockerfile_parseable', 0, 13, 11).
python_method('TestDockerAutomatedExecution', 'test_docker_electron_run_sh_syntax', 0, 5, 4).
python_class('tests/test_ansible.py', 'TestGeneratedFileCorrectness').
python_method('TestGeneratedFileCorrectness', '_root', 0, 1, 2).
python_method('TestGeneratedFileCorrectness', 'test_elf_binaries_have_valid_header', 0, 11, 8).
python_method('TestGeneratedFileCorrectness', 'test_pe_executables_have_mz_header', 0, 9, 10).
python_method('TestGeneratedFileCorrectness', 'test_zip_packages_have_pk_magic', 0, 7, 8).
python_method('TestGeneratedFileCorrectness', 'test_snap_has_squashfs_magic', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_msi_has_ole_magic', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_deb_has_ar_magic', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_dmg_has_udif_trailer', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_apk_contains_android_manifest', 0, 5, 8).
python_method('TestGeneratedFileCorrectness', 'test_apk_manifest_is_valid_xml', 0, 8, 13).
python_method('TestGeneratedFileCorrectness', 'test_ipa_contains_payload', 0, 8, 10).
python_method('TestGeneratedFileCorrectness', 'test_aab_contains_bundle_config', 0, 4, 6).
python_method('TestGeneratedFileCorrectness', 'test_all_json_files_parseable', 0, 5, 10).
python_method('TestGeneratedFileCorrectness', 'test_package_json_has_required_fields', 0, 8, 9).
python_method('TestGeneratedFileCorrectness', 'test_package_json_scripts_section', 0, 7, 7).
python_method('TestGeneratedFileCorrectness', 'test_tauri_conf_json_schema', 0, 7, 5).
python_method('TestGeneratedFileCorrectness', 'test_capacitor_config_json_schema', 0, 5, 5).
python_method('TestGeneratedFileCorrectness', 'test_electron_package_json_build_config', 0, 5, 5).
python_method('TestGeneratedFileCorrectness', 'test_react_native_app_json', 0, 3, 5).
python_method('TestGeneratedFileCorrectness', 'test_all_yaml_files_parseable', 0, 6, 10).
python_method('TestGeneratedFileCorrectness', 'test_docker_compose_has_services', 0, 9, 10).
python_method('TestGeneratedFileCorrectness', 'test_docker_compose_healthcheck', 0, 7, 11).
python_method('TestGeneratedFileCorrectness', 'test_pactown_sandbox_yaml_schema', 0, 11, 11).
python_method('TestGeneratedFileCorrectness', 'test_all_python_files_valid_syntax', 0, 5, 11).
python_method('TestGeneratedFileCorrectness', 'test_fastapi_main_has_app_and_health', 0, 9, 8).
python_method('TestGeneratedFileCorrectness', 'test_flask_app_has_app_and_health', 0, 9, 8).
python_method('TestGeneratedFileCorrectness', 'test_flask_wsgi_has_import', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_all_js_files_not_empty', 0, 5, 10).
python_method('TestGeneratedFileCorrectness', 'test_express_index_has_routes', 0, 6, 4).
python_method('TestGeneratedFileCorrectness', 'test_electron_main_js_structure', 0, 5, 4).
python_method('TestGeneratedFileCorrectness', 'test_nextjs_pages_structure', 0, 3, 4).
python_method('TestGeneratedFileCorrectness', 'test_nextjs_api_health_endpoint', 0, 4, 4).
python_method('TestGeneratedFileCorrectness', 'test_vue_app_has_template', 0, 3, 4).
python_method('TestGeneratedFileCorrectness', 'test_vue_main_js_creates_app', 0, 4, 4).
python_method('TestGeneratedFileCorrectness', 'test_react_jsx_has_component', 0, 5, 4).
python_method('TestGeneratedFileCorrectness', 'test_react_main_jsx_renders_root', 0, 4, 5).
python_method('TestGeneratedFileCorrectness', 'test_html_files_have_valid_structure', 0, 9, 10).
python_method('TestGeneratedFileCorrectness', 'test_dist_html_references_assets', 0, 7, 7).
python_method('TestGeneratedFileCorrectness', 'test_css_files_have_style_rules', 0, 8, 9).
python_method('TestGeneratedFileCorrectness', 'test_all_dockerfiles_have_from_and_cmd', 0, 10, 13).
python_method('TestGeneratedFileCorrectness', 'test_dockerfiles_valid_instructions', 0, 10, 15).
python_method('TestGeneratedFileCorrectness', 'test_dockerfiles_use_non_root_user', 0, 7, 12).
python_method('TestGeneratedFileCorrectness', 'test_dockerfiles_have_healthcheck', 0, 7, 12).
python_method('TestGeneratedFileCorrectness', 'test_requirements_txt_valid', 0, 13, 13).
python_method('TestGeneratedFileCorrectness', 'test_requirements_match_framework', 0, 6, 8).
python_method('TestGeneratedFileCorrectness', 'test_pyinstaller_spec_files_valid', 0, 10, 7).
python_method('TestGeneratedFileCorrectness', 'test_pyinstaller_spec_references_main', 0, 8, 7).
python_method('TestGeneratedFileCorrectness', 'test_buildozer_spec_valid', 0, 6, 6).
python_method('TestGeneratedFileCorrectness', 'test_shell_scripts_have_shebang', 0, 6, 11).
python_method('TestGeneratedFileCorrectness', 'test_vite_configs_define_plugin', 0, 6, 4).
python_method('TestGeneratedFileCorrectness', 'test_build_outputs_match_source', 0, 7, 5).
python_method('TestGeneratedFileCorrectness', 'test_web_dist_has_js_and_css_assets', 0, 8, 6).
python_method('TestGeneratedFileCorrectness', 'test_all_services_have_metadata_or_build_config', 0, 12, 13).
python_method('TestGeneratedFileCorrectness', 'test_correctness_report', 0, 10, 13).
python_class('tests/test_cross_platform.py', 'TestDesktopElectronAllOS').
python_method('TestDesktopElectronAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopElectronAllOS', 'test_scaffold_creates_package_json_and_main_js', 1, 3, 3).
python_method('TestDesktopElectronAllOS', 'test_scaffold_package_json_has_all_os_targets', 1, 4, 4).
python_method('TestDesktopElectronAllOS', 'test_scaffold_main_js_has_no_sandbox', 1, 2, 3).
python_method('TestDesktopElectronAllOS', 'test_scaffold_electron_dev_deps', 1, 3, 5).
python_method('TestDesktopElectronAllOS', 'test_scaffold_app_id', 1, 2, 4).
python_method('TestDesktopElectronAllOS', 'test_scaffold_custom_window_size', 1, 3, 3).
python_method('TestDesktopElectronAllOS', 'test_artifacts_per_os', 2, 3, 7).
python_method('TestDesktopElectronAllOS', 'test_build_cmd_per_os', 1, 2, 3).
python_method('TestDesktopElectronAllOS', 'test_build_cmd_multi_os', 0, 3, 1).
python_method('TestDesktopElectronAllOS', 'test_linux_artifacts_include_launcher', 1, 4, 4).
python_method('TestDesktopElectronAllOS', 'test_all_os_artifacts_combined', 1, 3, 6).
python_class('tests/test_cross_platform.py', 'TestDesktopTauriAllOS').
python_method('TestDesktopTauriAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopTauriAllOS', 'test_scaffold_creates_tauri_conf', 1, 5, 5).
python_method('TestDesktopTauriAllOS', 'test_scaffold_custom_app_id', 1, 2, 4).
python_method('TestDesktopTauriAllOS', 'test_scaffold_custom_window_size', 1, 3, 4).
python_method('TestDesktopTauriAllOS', 'test_artifacts_per_os', 2, 3, 6).
python_method('TestDesktopTauriAllOS', 'test_build_cmd', 0, 2, 1).
python_method('TestDesktopTauriAllOS', 'test_all_os_artifacts_combined', 1, 3, 5).
python_class('tests/test_cross_platform.py', 'TestDesktopPyInstallerAllOS').
python_method('TestDesktopPyInstallerAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopPyInstallerAllOS', 'test_scaffold_creates_spec', 1, 2, 4).
python_method('TestDesktopPyInstallerAllOS', 'test_scaffold_with_icon', 1, 2, 3).
python_method('TestDesktopPyInstallerAllOS', 'test_artifacts_per_os', 2, 3, 6).
python_method('TestDesktopPyInstallerAllOS', 'test_build_cmd_same_for_all_os', 1, 2, 2).
python_method('TestDesktopPyInstallerAllOS', 'test_all_os_artifacts_combined', 1, 3, 5).
python_class('tests/test_cross_platform.py', 'TestDesktopPyQtAllOS').
python_method('TestDesktopPyQtAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopPyQtAllOS', 'test_scaffold_creates_spec', 1, 2, 4).
python_method('TestDesktopPyQtAllOS', 'test_artifacts_per_os', 2, 3, 6).
python_method('TestDesktopPyQtAllOS', 'test_build_cmd_same_for_all_os', 1, 2, 2).
python_class('tests/test_cross_platform.py', 'TestDesktopTkinterAllOS').
python_method('TestDesktopTkinterAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopTkinterAllOS', 'test_scaffold_creates_spec', 1, 2, 3).
python_method('TestDesktopTkinterAllOS', 'test_artifacts_per_os', 2, 3, 6).
python_method('TestDesktopTkinterAllOS', 'test_build_cmd_same_for_all_os', 1, 2, 2).
python_class('tests/test_cross_platform.py', 'TestDesktopFlutterAllOS').
python_method('TestDesktopFlutterAllOS', 'sandbox', 1, 1, 2).
python_method('TestDesktopFlutterAllOS', 'test_scaffold_noop', 1, 1, 3).
python_method('TestDesktopFlutterAllOS', 'test_artifacts_per_os', 2, 3, 4).
python_method('TestDesktopFlutterAllOS', 'test_build_cmd_per_os', 1, 2, 2).
python_class('tests/test_cross_platform.py', 'TestMobileCapacitorAllPlatforms').
python_method('TestMobileCapacitorAllPlatforms', 'sandbox', 1, 1, 2).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_creates_config', 1, 3, 3).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_config_content', 1, 4, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_custom_app_id', 1, 2, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_package_json_deps', 1, 3, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_android_platform_dep', 1, 2, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_ios_platform_dep', 1, 2, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_dual_platform_deps', 1, 3, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_scripts', 1, 4, 4).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_web_dir_detection_dist', 1, 2, 6).
python_method('TestMobileCapacitorAllPlatforms', 'test_scaffold_web_dir_detection_root', 1, 2, 5).
python_method('TestMobileCapacitorAllPlatforms', 'test_artifacts_per_platform', 2, 2, 6).
python_method('TestMobileCapacitorAllPlatforms', 'test_build_cmd_per_platform', 1, 5, 2).
python_method('TestMobileCapacitorAllPlatforms', 'test_dual_platform_artifacts', 1, 5, 6).
python_class('tests/test_cross_platform.py', 'TestMobileReactNativeAllPlatforms').
python_method('TestMobileReactNativeAllPlatforms', 'sandbox', 1, 1, 2).
python_method('TestMobileReactNativeAllPlatforms', 'test_scaffold_creates_app_json', 1, 2, 3).
python_method('TestMobileReactNativeAllPlatforms', 'test_scaffold_app_json_content', 1, 3, 4).
python_method('TestMobileReactNativeAllPlatforms', 'test_scaffold_custom_display_name', 1, 2, 4).
python_method('TestMobileReactNativeAllPlatforms', 'test_artifacts_per_platform', 2, 2, 6).
python_method('TestMobileReactNativeAllPlatforms', 'test_build_cmd_android', 0, 2, 1).
python_method('TestMobileReactNativeAllPlatforms', 'test_build_cmd_ios', 0, 2, 1).
python_method('TestMobileReactNativeAllPlatforms', 'test_dual_platform_artifacts', 1, 5, 6).
python_class('tests/test_cross_platform.py', 'TestMobileFlutterAllPlatforms').
python_method('TestMobileFlutterAllPlatforms', 'sandbox', 1, 1, 2).
python_method('TestMobileFlutterAllPlatforms', 'test_scaffold_noop', 1, 1, 3).
python_method('TestMobileFlutterAllPlatforms', 'test_artifacts_per_platform', 2, 2, 4).
python_method('TestMobileFlutterAllPlatforms', 'test_build_cmd_android', 0, 2, 1).
python_method('TestMobileFlutterAllPlatforms', 'test_build_cmd_ios', 0, 2, 1).
python_class('tests/test_cross_platform.py', 'TestMobileKivyAllPlatforms').
python_method('TestMobileKivyAllPlatforms', 'sandbox', 1, 1, 2).
python_method('TestMobileKivyAllPlatforms', 'test_scaffold_creates_buildozer_spec', 1, 4, 4).
python_method('TestMobileKivyAllPlatforms', 'test_scaffold_custom_app_id', 1, 2, 3).
python_method('TestMobileKivyAllPlatforms', 'test_scaffold_fullscreen', 1, 2, 3).
python_method('TestMobileKivyAllPlatforms', 'test_scaffold_no_fullscreen', 1, 2, 3).
python_method('TestMobileKivyAllPlatforms', 'test_scaffold_icon', 1, 2, 3).
python_method('TestMobileKivyAllPlatforms', 'test_artifacts_per_platform', 2, 2, 6).
python_method('TestMobileKivyAllPlatforms', 'test_build_cmd_android', 0, 2, 1).
python_method('TestMobileKivyAllPlatforms', 'test_build_cmd_ios', 0, 2, 1).
python_method('TestMobileKivyAllPlatforms', 'test_android_apk_and_aab', 1, 4, 4).
python_class('tests/test_cross_platform.py', 'TestWebAllFrameworks').
python_method('TestWebAllFrameworks', 'sandbox', 1, 1, 2).
python_method('TestWebAllFrameworks', 'test_scaffold_noop', 2, 1, 3).
python_method('TestWebAllFrameworks', 'test_build_no_cmd_returns_success', 2, 3, 3).
python_method('TestWebAllFrameworks', 'test_build_with_cmd_runs_shell', 2, 3, 3).
python_method('TestWebAllFrameworks', 'test_platform_name', 0, 2, 1).
python_class('tests/test_cross_platform.py', 'TestAnsibleDeployDesktopAllCombinations').
python_method('TestAnsibleDeployDesktopAllCombinations', 'test_scaffold_artifacts_ansible_deploy', 3, 9, 13).
python_class('tests/test_cross_platform.py', 'TestAnsibleDeployMobileAllCombinations').
python_method('TestAnsibleDeployMobileAllCombinations', 'test_scaffold_artifacts_ansible_deploy', 3, 9, 12).
python_class('tests/test_cross_platform.py', 'TestAnsibleDeployWebAllFrameworks').
python_method('TestAnsibleDeployWebAllFrameworks', 'test_web_framework_ansible_deploy', 2, 5, 10).
python_class('tests/test_cross_platform.py', 'TestFrameworkRegistryCompleteness').
python_method('TestFrameworkRegistryCompleteness', 'test_all_desktop_frameworks_registered', 0, 4, 1).
python_method('TestFrameworkRegistryCompleteness', 'test_all_mobile_frameworks_registered', 0, 4, 1).
python_method('TestFrameworkRegistryCompleteness', 'test_all_frameworks_have_build_cmd', 0, 3, 1).
python_method('TestFrameworkRegistryCompleteness', 'test_all_frameworks_have_artifact_patterns', 0, 3, 1).
python_method('TestFrameworkRegistryCompleteness', 'test_desktop_enums_match_registry', 0, 3, 0).
python_method('TestFrameworkRegistryCompleteness', 'test_mobile_enums_match_registry', 0, 3, 0).
python_method('TestFrameworkRegistryCompleteness', 'test_web_enums', 0, 3, 0).
python_class('tests/test_cross_platform.py', 'TestBuildCommandMatrix').
python_method('TestBuildCommandMatrix', 'test_electron_build_cmd_targets', 1, 3, 3).
python_method('TestBuildCommandMatrix', 'test_tauri_build_cmd_ignores_targets', 0, 3, 1).
python_method('TestBuildCommandMatrix', 'test_python_desktop_build_cmd', 1, 3, 2).
python_method('TestBuildCommandMatrix', 'test_flutter_desktop_build_cmd', 1, 2, 2).
python_method('TestBuildCommandMatrix', 'test_capacitor_build_cmd', 1, 5, 2).
python_method('TestBuildCommandMatrix', 'test_react_native_build_cmd', 1, 3, 2).
python_method('TestBuildCommandMatrix', 'test_flutter_mobile_build_cmd', 1, 2, 2).
python_method('TestBuildCommandMatrix', 'test_kivy_build_cmd', 1, 2, 2).
python_method('TestBuildCommandMatrix', 'test_unknown_desktop_framework_returns_empty', 0, 2, 1).
python_method('TestBuildCommandMatrix', 'test_unknown_mobile_framework_returns_empty', 0, 2, 1).
python_class('tests/test_cross_platform.py', 'TestArtifactCollectionMatrix').
python_method('TestArtifactCollectionMatrix', 'test_desktop_artifact_collection', 3, 5, 8).
python_method('TestArtifactCollectionMatrix', 'test_flutter_desktop_linux_artifacts', 1, 2, 4).
python_method('TestArtifactCollectionMatrix', 'test_mobile_artifact_collection', 3, 5, 8).
python_method('TestArtifactCollectionMatrix', 'test_flutter_mobile_android_artifacts', 1, 2, 4).
python_method('TestArtifactCollectionMatrix', 'test_unknown_desktop_framework_fallback', 1, 2, 4).
python_method('TestArtifactCollectionMatrix', 'test_unknown_mobile_framework_fallback', 1, 2, 4).
python_method('TestArtifactCollectionMatrix', 'test_empty_sandbox_returns_no_artifacts', 1, 3, 2).
python_class('tests/test_cross_platform.py', 'TestElectronNoSandboxAllPatterns').
python_method('TestElectronNoSandboxAllPatterns', 'test_commonjs_require', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_commonjs_double_quotes', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_es_module_single_quotes', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_es_module_double_quotes', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_app_whenready_fallback', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_app_on_fallback', 1, 3, 4).
python_method('TestElectronNoSandboxAllPatterns', 'test_ultimate_fallback_prepend', 1, 4, 5).
python_method('TestElectronNoSandboxAllPatterns', 'test_skip_already_patched', 1, 2, 3).
python_method('TestElectronNoSandboxAllPatterns', 'test_no_main_js', 1, 2, 2).
python_class('tests/test_cross_platform.py', 'TestElectronBuilderFlagFilteringAllOS').
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_linux_host_keeps_linux', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_linux_host_strips_mac', 2, 3, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_linux_host_strips_windows_no_wine', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_linux_host_keeps_windows_with_wine', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_linux_host_multi_target', 2, 4, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_macos_host_keeps_mac', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_macos_host_keeps_linux', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_windows_host_keeps_windows', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_windows_host_strips_mac', 2, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_empty_targets_defaults_to_linux', 0, 2, 1).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_none_targets_defaults_to_linux', 0, 2, 1).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_no_duplicates', 0, 2, 2).
python_method('TestElectronBuilderFlagFilteringAllOS', 'test_filter_cmd_strips_unsupported', 0, 3, 2).
python_class('tests/test_cross_platform.py', 'TestElectronParallelBuild').
python_method('TestElectronParallelBuild', 'test_single_target_falls_back_to_sequential', 1, 2, 4).
python_method('TestElectronParallelBuild', 'test_non_electron_falls_back_to_sequential', 1, 2, 3).
python_class('tests/test_cross_platform.py', 'TestFullE2EAllDesktopCombinations').
python_method('TestFullE2EAllDesktopCombinations', 'test_all_os_e2e', 2, 7, 11).
python_class('tests/test_cross_platform.py', 'TestFullE2EAllMobileCombinations').
python_method('TestFullE2EAllMobileCombinations', 'test_all_platforms_e2e', 2, 7, 11).
python_class('tests/test_deploy_optimizations.py', 'TestNpmCiSelection').
python_method('TestNpmCiSelection', 'test_npm_install_when_no_lock', 1, 4, 4).
python_method('TestNpmCiSelection', 'test_npm_ci_when_lock_exists', 1, 4, 3).
python_method('TestNpmCiSelection', 'test_prefer_offline_only_without_lock', 0, 5, 1).
python_class('tests/test_deploy_optimizations.py', 'TestElectronLazyScaffold').
python_method('TestElectronLazyScaffold', 'test_already_scaffolded_returns_true', 1, 2, 3).
python_method('TestElectronLazyScaffold', 'test_not_scaffolded_no_main_js', 1, 2, 3).
python_method('TestElectronLazyScaffold', 'test_not_scaffolded_missing_electron', 1, 2, 3).
python_method('TestElectronLazyScaffold', 'test_not_scaffolded_no_package_json', 1, 2, 2).
python_method('TestElectronLazyScaffold', 'test_not_scaffolded_invalid_json', 1, 2, 2).
python_method('TestElectronLazyScaffold', 'test_scaffold_skips_when_already_done', 1, 6, 7).
python_method('TestElectronLazyScaffold', 'test_scaffold_runs_when_not_done', 1, 3, 5).
python_class('tests/test_deploy_optimizations.py', 'TestParallelMultiTargetBuild').
python_method('TestParallelMultiTargetBuild', 'test_single_target_falls_back_to_sequential', 1, 3, 3).
python_method('TestParallelMultiTargetBuild', 'test_non_electron_falls_back', 1, 2, 3).
python_method('TestParallelMultiTargetBuild', 'test_explicit_build_cmd_falls_back', 1, 2, 2).
python_method('TestParallelMultiTargetBuild', 'test_parallel_electron_multi_target', 1, 2, 5).
python_method('TestParallelMultiTargetBuild', 'test_parallel_result_has_correct_fields', 1, 5, 3).
python_class('tests/test_deploy_optimizations.py', 'TestBuildLogStreaming').
python_method('TestBuildLogStreaming', 'test_stderr_merged_into_stdout', 1, 5, 3).
python_method('TestBuildLogStreaming', 'test_on_log_receives_lines_in_order', 1, 2, 2).
python_method('TestBuildLogStreaming', 'test_build_error_visible_in_logs', 1, 3, 3).
python_class('tests/test_deploy_optimizations.py', 'TestIncrementalBuilds').
python_method('TestIncrementalBuilds', '_build', 3, 1, 5).
python_method('TestIncrementalBuilds', 'test_first_build_creates_hash_file', 1, 4, 5).
python_method('TestIncrementalBuilds', 'test_second_build_is_incremental', 1, 4, 3).
python_method('TestIncrementalBuilds', 'test_changed_readme_triggers_full_rebuild', 1, 4, 4).
python_method('TestIncrementalBuilds', 'test_incremental_still_scaffolds', 1, 4, 2).
python_class('tests/test_deploy_optimizations.py', 'TestCacheDirectories').
python_method('TestCacheDirectories', 'test_all_cache_dirs_created', 1, 3, 2).
python_method('TestCacheDirectories', 'test_electron_builder_cache_created_on_build', 1, 2, 7).
python_class('tests/test_deploy_optimizations.py', 'TestElectronPinnedVersions').
python_method('TestElectronPinnedVersions', 'test_ensure_electron_dev_deps_uses_pinned', 1, 5, 2).
python_method('TestElectronPinnedVersions', 'test_existing_version_not_overwritten', 1, 4, 1).
python_class('tests/test_deploy_optimizations.py', 'TestRunShellContract').
python_method('TestRunShellContract', 'test_success_returns_zero', 1, 4, 1).
python_method('TestRunShellContract', 'test_failure_returns_nonzero', 1, 2, 1).
python_method('TestRunShellContract', 'test_stderr_merged', 1, 4, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopElectron').
python_method('TestDeployDesktopElectron', 'test_sandbox_creation', 1, 5, 2).
python_method('TestDeployDesktopElectron', 'test_target_parsing', 0, 5, 2).
python_method('TestDeployDesktopElectron', 'test_scaffold_creates_package_json_and_main_js', 1, 6, 6).
python_method('TestDeployDesktopElectron', 'test_build_produces_artifacts', 1, 7, 10).
python_method('TestDeployDesktopElectron', 'test_build_result_has_logs', 1, 3, 4).
python_method('TestDeployDesktopElectron', 'test_iac_spec_for_electron', 1, 3, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopTauri').
python_method('TestDeployDesktopTauri', 'test_scaffold_creates_tauri_conf', 1, 4, 5).
python_method('TestDeployDesktopTauri', 'test_full_build', 1, 4, 6).
python_method('TestDeployDesktopTauri', 'test_default_build_cmd', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopPyInstaller').
python_method('TestDeployDesktopPyInstaller', 'test_scaffold_creates_spec', 1, 3, 4).
python_method('TestDeployDesktopPyInstaller', 'test_full_build', 1, 4, 6).
python_method('TestDeployDesktopPyInstaller', 'test_sandbox_writes_requirements', 1, 4, 3).
python_method('TestDeployDesktopPyInstaller', 'test_iac_python_runtime', 1, 3, 4).
python_method('TestDeployDesktopPyInstaller', 'test_dockerfile_generation', 1, 4, 3).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopPyQt').
python_method('TestDeployDesktopPyQt', 'test_scaffold_creates_spec_with_icon', 1, 4, 4).
python_method('TestDeployDesktopPyQt', 'test_full_build', 1, 4, 5).
python_method('TestDeployDesktopPyQt', 'test_framework_meta', 0, 5, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopTkinter').
python_method('TestDeployDesktopTkinter', 'test_scaffold_and_build', 1, 3, 6).
python_method('TestDeployDesktopTkinter', 'test_default_cmd_uses_pyinstaller', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployDesktopFlutter').
python_method('TestDeployDesktopFlutter', 'test_parse_and_build', 1, 4, 6).
python_method('TestDeployDesktopFlutter', 'test_default_cmd', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployMobileCapacitor').
python_method('TestDeployMobileCapacitor', 'test_scaffold_creates_capacitor_config', 1, 5, 5).
python_method('TestDeployMobileCapacitor', 'test_scaffold_creates_package_json_scripts', 1, 3, 4).
python_method('TestDeployMobileCapacitor', 'test_full_build', 1, 4, 6).
python_method('TestDeployMobileCapacitor', 'test_builder_registry', 0, 2, 3).
python_method('TestDeployMobileCapacitor', 'test_iac_node_runtime', 1, 3, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployMobileReactNative').
python_method('TestDeployMobileReactNative', 'test_scaffold_creates_app_json', 1, 3, 5).
python_method('TestDeployMobileReactNative', 'test_full_build', 1, 4, 6).
python_method('TestDeployMobileReactNative', 'test_default_cmd_android', 0, 2, 1).
python_method('TestDeployMobileReactNative', 'test_default_cmd_ios', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployMobileKivy').
python_method('TestDeployMobileKivy', 'test_scaffold_creates_buildozer_spec', 1, 4, 4).
python_method('TestDeployMobileKivy', 'test_full_build', 1, 4, 8).
python_method('TestDeployMobileKivy', 'test_sandbox_creates_requirements', 1, 5, 3).
python_method('TestDeployMobileKivy', 'test_iac_python_runtime', 1, 3, 4).
python_class('tests/test_deploy_platforms.py', 'TestDeployMobileFlutter').
python_method('TestDeployMobileFlutter', 'test_parse', 0, 5, 2).
python_method('TestDeployMobileFlutter', 'test_build', 1, 3, 6).
python_method('TestDeployMobileFlutter', 'test_default_cmd_android', 0, 2, 1).
python_method('TestDeployMobileFlutter', 'test_default_cmd_ios', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDeployWebFastAPI').
python_method('TestDeployWebFastAPI', 'test_sandbox_creation', 1, 5, 3).
python_method('TestDeployWebFastAPI', 'test_iac_manifest', 1, 3, 4).
python_method('TestDeployWebFastAPI', 'test_dockerfile_python_image', 1, 5, 3).
python_method('TestDeployWebFastAPI', 'test_compose_yaml', 1, 4, 4).
python_method('TestDeployWebFastAPI', 'test_web_builder_no_artifacts', 1, 3, 2).
python_method('TestDeployWebFastAPI', 'test_run_cmd_extracted', 0, 3, 2).
python_class('tests/test_deploy_platforms.py', 'TestDeployWebFlask').
python_method('TestDeployWebFlask', 'test_sandbox_creation', 1, 5, 3).
python_method('TestDeployWebFlask', 'test_iac_manifest_python', 1, 3, 3).
python_method('TestDeployWebFlask', 'test_dockerfile_python', 1, 3, 2).
python_method('TestDeployWebFlask', 'test_compose_with_port', 1, 2, 3).
python_class('tests/test_deploy_platforms.py', 'TestDeployWebExpress').
python_method('TestDeployWebExpress', 'test_sandbox_creates_package_json', 1, 4, 5).
python_method('TestDeployWebExpress', 'test_iac_manifest_node', 1, 2, 3).
python_method('TestDeployWebExpress', 'test_dockerfile_node_image', 1, 3, 2).
python_method('TestDeployWebExpress', 'test_compose_healthcheck_node', 1, 3, 2).
python_class('tests/test_deploy_platforms.py', 'TestDeployWebStatic').
python_method('TestDeployWebStatic', 'test_sandbox_no_deps', 1, 3, 2).
python_method('TestDeployWebStatic', 'test_iac_manifest', 1, 3, 3).
python_method('TestDeployWebStatic', 'test_web_builder_build_step', 1, 3, 5).
python_class('tests/test_deploy_platforms.py', 'TestIaCSpecAllPlatforms').
python_method('TestIaCSpecAllPlatforms', 'test_python_web_spec', 0, 8, 2).
python_method('TestIaCSpecAllPlatforms', 'test_node_web_spec', 0, 3, 2).
python_method('TestIaCSpecAllPlatforms', 'test_desktop_electron_spec', 0, 3, 2).
python_method('TestIaCSpecAllPlatforms', 'test_mobile_kivy_spec', 0, 3, 2).
python_method('TestIaCSpecAllPlatforms', 'test_mobile_capacitor_spec', 0, 2, 2).
python_class('tests/test_deploy_platforms.py', 'TestComposeHealthcheckPerPlatform').
python_method('TestComposeHealthcheckPerPlatform', 'test_python_healthcheck_uses_urllib', 0, 3, 2).
python_method('TestComposeHealthcheckPerPlatform', 'test_node_healthcheck_uses_http_module', 0, 3, 2).
python_method('TestComposeHealthcheckPerPlatform', 'test_no_port_no_port_mapping', 0, 2, 1).
python_class('tests/test_deploy_platforms.py', 'TestDockerfilePerPlatform').
python_method('TestDockerfilePerPlatform', 'test_python_dockerfile', 1, 5, 4).
python_method('TestDockerfilePerPlatform', 'test_node_dockerfile', 1, 4, 4).
python_method('TestDockerfilePerPlatform', 'test_python_no_deps_no_requirements_copy', 1, 3, 3).
python_method('TestDockerfilePerPlatform', 'test_python_dockerfile_run_cmd_none', 1, 2, 4).
python_method('TestDockerfilePerPlatform', 'test_node_dockerfile_run_cmd_none', 1, 2, 4).
python_class('tests/test_deploy_platforms.py', 'TestBuildServiceIntegration').
python_method('TestBuildServiceIntegration', '_build', 5, 1, 6).
python_method('TestBuildServiceIntegration', 'test_electron_build_service', 1, 3, 1).
python_method('TestBuildServiceIntegration', 'test_pyinstaller_build_service', 1, 2, 1).
python_method('TestBuildServiceIntegration', 'test_capacitor_build_service', 1, 3, 1).
python_method('TestBuildServiceIntegration', 'test_kivy_build_service', 1, 2, 1).
python_method('TestBuildServiceIntegration', 'test_web_build_service', 1, 3, 1).
python_method('TestBuildServiceIntegration', 'test_build_failure_propagated', 1, 3, 2).
python_method('TestBuildServiceIntegration', 'test_build_env_contains_electron_builder_cache', 1, 3, 8).
python_class('tests/test_deploy_platforms.py', 'TestNodeModulesCacheIntegration').
python_method('TestNodeModulesCacheIntegration', 'test_node_cache_initialized', 1, 3, 2).
python_method('TestNodeModulesCacheIntegration', 'test_cache_dir_created', 1, 2, 2).
python_method('TestNodeModulesCacheIntegration', 'test_dep_cache_initialized', 1, 3, 2).
python_class('tests/test_deploy_platforms.py', 'TestFrameworkMetaDeploymentReady').
python_method('TestFrameworkMetaDeploymentReady', 'test_framework_has_build_cmd', 1, 3, 2).
python_method('TestFrameworkMetaDeploymentReady', 'test_framework_has_artifact_patterns', 1, 3, 2).
python_method('TestFrameworkMetaDeploymentReady', 'test_framework_platform_correct', 2, 2, 2).
python_class('tests/test_e2e_build.py', 'TestE2EDesktopElectron').
python_method('TestE2EDesktopElectron', 'test_parse_all_blocks', 1, 9, 3).
python_method('TestE2EDesktopElectron', 'test_scaffold_creates_package_json', 1, 6, 8).
python_method('TestE2EDesktopElectron', 'test_full_build_with_dummy_cmd', 1, 7, 9).
python_method('TestE2EDesktopElectron', 'test_builder_registry_resolves_desktop', 1, 2, 4).
python_class('tests/test_e2e_build.py', 'TestE2EDesktopPyInstaller').
python_method('TestE2EDesktopPyInstaller', 'test_full_pipeline', 1, 10, 8).
python_class('tests/test_e2e_build.py', 'TestE2EDesktopTauri').
python_method('TestE2EDesktopTauri', 'test_scaffold_and_parse', 1, 7, 8).
python_class('tests/test_e2e_build.py', 'TestE2EMobileCapacitor').
python_method('TestE2EMobileCapacitor', 'test_full_pipeline', 1, 10, 10).
python_class('tests/test_e2e_build.py', 'TestE2EMobileKivy').
python_method('TestE2EMobileKivy', 'test_full_pipeline', 1, 10, 9).
python_class('tests/test_e2e_build.py', 'TestE2EWebBuilder').
python_method('TestE2EWebBuilder', 'test_web_no_target_block_defaults_to_web', 1, 4, 4).
python_method('TestE2EWebBuilder', 'test_web_build_succeeds_without_cmd', 1, 3, 2).
python_method('TestE2EWebBuilder', 'test_web_build_with_optional_step', 1, 3, 4).
python_class('tests/test_e2e_build.py', 'TestE2EServiceConfigTargets').
python_method('TestE2EServiceConfigTargets', 'test_service_config_from_dict_with_target', 0, 5, 1).
python_method('TestE2EServiceConfigTargets', 'test_service_config_defaults_to_web', 0, 5, 1).
python_method('TestE2EServiceConfigTargets', 'test_service_config_build_targets_as_csv_string', 0, 2, 1).
python_class('tests/test_e2e_build.py', 'TestE2ECrossPlatformScenario').
python_method('TestE2ECrossPlatformScenario', 'test_same_app_different_platforms', 1, 5, 5).
python_method('TestE2ECrossPlatformScenario', 'test_build_failure_returns_failed_result', 1, 4, 3).
python_class('tests/test_e2e_build_extended.py', 'TestElectronDevDepsRegression').
python_method('TestElectronDevDepsRegression', 'test_new_package_json_has_electron_in_dev_deps', 1, 3, 5).
python_method('TestElectronDevDepsRegression', 'test_existing_package_json_gets_electron_added', 1, 4, 7).
python_method('TestElectronDevDepsRegression', 'test_electron_moved_from_deps_to_dev_deps', 1, 5, 7).
python_method('TestElectronDevDepsRegression', 'test_ensure_electron_dev_deps_idempotent', 1, 3, 6).
python_class('tests/test_e2e_build_extended.py', 'TestE2EDesktopPyQt').
python_method('TestE2EDesktopPyQt', 'test_parse_pyqt_target', 1, 7, 2).
python_method('TestE2EDesktopPyQt', 'test_scaffold_creates_spec_with_icon', 1, 4, 5).
python_method('TestE2EDesktopPyQt', 'test_full_build', 1, 4, 8).
python_method('TestE2EDesktopPyQt', 'test_builder_registry_resolves', 1, 2, 4).
python_class('tests/test_e2e_build_extended.py', 'TestE2EDesktopTkinter').
python_method('TestE2EDesktopTkinter', 'test_parse_and_scaffold', 1, 5, 7).
python_method('TestE2EDesktopTkinter', 'test_full_build', 1, 4, 7).
python_class('tests/test_e2e_build_extended.py', 'TestE2EDesktopTauriBuild').
python_method('TestE2EDesktopTauriBuild', 'test_scaffold_with_window_size', 1, 5, 8).
python_method('TestE2EDesktopTauriBuild', 'test_full_build_with_artifact_collection', 1, 6, 8).
python_class('tests/test_e2e_build_extended.py', 'TestE2EMobileReactNative').
python_method('TestE2EMobileReactNative', 'test_parse_react_native', 1, 8, 2).
python_method('TestE2EMobileReactNative', 'test_scaffold_creates_app_json', 1, 4, 6).
python_method('TestE2EMobileReactNative', 'test_scaffold_react_native_custom_display_name', 1, 2, 5).
python_method('TestE2EMobileReactNative', 'test_full_build', 1, 4, 8).
python_method('TestE2EMobileReactNative', 'test_builder_registry_resolves_mobile', 1, 2, 4).
python_class('tests/test_e2e_build_extended.py', 'TestE2EMobileFlutter').
python_method('TestE2EMobileFlutter', 'test_parse_flutter_mobile', 1, 5, 2).
python_method('TestE2EMobileFlutter', 'test_scaffold_flutter_is_noop', 1, 2, 5).
python_method('TestE2EMobileFlutter', 'test_full_build', 1, 4, 8).
python_class('tests/test_e2e_build_extended.py', 'TestE2EDesktopFlutter').
python_method('TestE2EDesktopFlutter', 'test_parse', 1, 3, 2).
python_method('TestE2EDesktopFlutter', 'test_full_build', 1, 4, 7).
python_class('tests/test_e2e_build_extended.py', 'TestArtifactCollection').
python_method('TestArtifactCollection', 'test_electron_artifacts', 1, 6, 3).
python_method('TestArtifactCollection', 'test_pyinstaller_artifacts', 1, 3, 4).
python_method('TestArtifactCollection', 'test_capacitor_apk_artifacts', 1, 3, 4).
python_method('TestArtifactCollection', 'test_kivy_artifacts', 1, 4, 3).
python_method('TestArtifactCollection', 'test_react_native_artifacts', 1, 2, 4).
python_method('TestArtifactCollection', 'test_flutter_mobile_artifacts', 1, 2, 4).
python_method('TestArtifactCollection', 'test_no_artifacts_empty_dir', 1, 2, 1).
python_method('TestArtifactCollection', 'test_tauri_artifacts', 1, 3, 4).
python_class('tests/test_e2e_build_extended.py', 'TestDefaultBuildCmdResolution').
python_method('TestDefaultBuildCmdResolution', 'test_desktop_electron_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_desktop_tauri_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_desktop_pyinstaller_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_desktop_pyqt_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_desktop_flutter_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_desktop_flutter_default_cmd_no_targets', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_capacitor_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_react_native_android_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_react_native_ios_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_flutter_android_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_flutter_ios_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_kivy_default_cmd', 0, 2, 1).
python_method('TestDefaultBuildCmdResolution', 'test_unknown_framework_returns_empty', 0, 3, 1).
python_method('TestDefaultBuildCmdResolution', 'test_no_cmd_no_framework_returns_failed_result', 1, 3, 3).
python_method('TestDefaultBuildCmdResolution', 'test_mobile_no_cmd_no_framework_returns_failed_result', 1, 3, 3).
python_class('tests/test_e2e_build_extended.py', 'TestOnLogCallback').
python_method('TestOnLogCallback', 'test_desktop_build_streams_logs', 1, 3, 3).
python_method('TestOnLogCallback', 'test_mobile_build_streams_logs', 1, 3, 3).
python_method('TestOnLogCallback', 'test_web_build_streams_logs', 1, 3, 3).
python_method('TestOnLogCallback', 'test_scaffold_sends_log', 1, 2, 4).
python_method('TestOnLogCallback', 'test_broken_on_log_does_not_crash', 1, 2, 3).
python_class('tests/test_e2e_build_extended.py', 'TestBuildWithEnvVars').
python_method('TestBuildWithEnvVars', 'test_env_passed_to_build_cmd', 1, 3, 3).
python_method('TestBuildWithEnvVars', 'test_mobile_env_passed', 1, 2, 2).
python_class('tests/test_e2e_build_extended.py', 'TestScaffoldIdempotency').
python_method('TestScaffoldIdempotency', 'test_electron_scaffold_twice', 1, 3, 5).
python_method('TestScaffoldIdempotency', 'test_tauri_scaffold_twice', 1, 2, 3).
python_method('TestScaffoldIdempotency', 'test_capacitor_scaffold_twice', 1, 2, 3).
python_method('TestScaffoldIdempotency', 'test_kivy_scaffold_twice', 1, 2, 3).
python_method('TestScaffoldIdempotency', 'test_pyinstaller_scaffold_twice', 1, 2, 3).
python_method('TestScaffoldIdempotency', 'test_react_native_scaffold_twice', 1, 2, 3).
python_class('tests/test_e2e_build_extended.py', 'TestUnknownFrameworkFallback').
python_method('TestUnknownFrameworkFallback', 'test_desktop_unknown_framework_scaffold_noop', 1, 2, 4).
python_method('TestUnknownFrameworkFallback', 'test_mobile_unknown_framework_scaffold_noop', 1, 2, 4).
python_method('TestUnknownFrameworkFallback', 'test_desktop_empty_framework_scaffold_noop', 1, 2, 4).
python_method('TestUnknownFrameworkFallback', 'test_mobile_empty_framework_scaffold_noop', 1, 2, 4).
python_class('tests/test_e2e_build_extended.py', 'TestTargetConfigEdgeCases').
python_method('TestTargetConfigEdgeCases', 'test_from_dict_unknown_platform_defaults_to_web', 0, 2, 1).
python_method('TestTargetConfigEdgeCases', 'test_targets_as_csv_string', 0, 2, 1).
python_method('TestTargetConfigEdgeCases', 'test_effective_build_targets_defaults', 0, 4, 2).
python_method('TestTargetConfigEdgeCases', 'test_effective_build_targets_explicit', 0, 2, 2).
python_method('TestTargetConfigEdgeCases', 'test_is_buildable', 0, 4, 1).
python_method('TestTargetConfigEdgeCases', 'test_needs_port', 0, 4, 1).
python_method('TestTargetConfigEdgeCases', 'test_extra_fields_preserved', 0, 2, 1).
python_method('TestTargetConfigEdgeCases', 'test_window_dimensions_parsed_as_int', 0, 3, 1).
python_method('TestTargetConfigEdgeCases', 'test_window_dimensions_invalid_returns_none', 0, 2, 1).
python_class('tests/test_e2e_build_extended.py', 'TestFrameworkRegistry').
python_method('TestFrameworkRegistry', 'test_all_desktop_frameworks_registered', 0, 4, 1).
python_method('TestFrameworkRegistry', 'test_all_mobile_frameworks_registered', 0, 4, 1).
python_method('TestFrameworkRegistry', 'test_flutter_desktop_registered', 0, 3, 1).
python_method('TestFrameworkRegistry', 'test_flutter_mobile_registered', 0, 3, 1).
python_method('TestFrameworkRegistry', 'test_case_insensitive_lookup', 0, 4, 1).
python_method('TestFrameworkRegistry', 'test_unknown_framework_returns_none', 0, 4, 1).
python_method('TestFrameworkRegistry', 'test_list_frameworks_all', 0, 2, 2).
python_method('TestFrameworkRegistry', 'test_list_frameworks_desktop', 0, 3, 3).
python_method('TestFrameworkRegistry', 'test_list_frameworks_mobile', 0, 3, 3).
python_method('TestFrameworkRegistry', 'test_node_frameworks_have_needs_node_true', 0, 3, 1).
python_method('TestFrameworkRegistry', 'test_python_frameworks_have_needs_python_true', 0, 3, 1).
python_method('TestFrameworkRegistry', 'test_every_framework_has_default_build_cmd', 0, 3, 1).
python_class('tests/test_e2e_build_extended.py', 'TestInferTargetFromDeps').
python_method('TestInferTargetFromDeps', 'test_electron_dep_infers_desktop', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_pyqt_dep_infers_desktop', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_capacitor_dep_infers_mobile', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_react_native_dep_infers_mobile', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_buildozer_dep_infers_mobile', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_fastapi_dep_infers_web', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_empty_deps_infers_web', 0, 2, 1).
python_method('TestInferTargetFromDeps', 'test_mobile_takes_priority_over_desktop', 0, 2, 1).
python_class('tests/test_e2e_build_extended.py', 'TestExtractRunCommand').
python_method('TestExtractRunCommand', 'test_explicit_run_block', 1, 2, 4).
python_method('TestExtractRunCommand', 'test_framework_default_run_cmd', 1, 3, 4).
python_method('TestExtractRunCommand', 'test_file_heuristic_main_py', 1, 2, 4).
python_method('TestExtractRunCommand', 'test_file_heuristic_index_js', 1, 2, 4).
python_method('TestExtractRunCommand', 'test_no_run_cmd_returns_none', 1, 2, 4).
python_class('tests/test_e2e_build_extended.py', 'TestBuildFailures').
python_method('TestBuildFailures', 'test_desktop_build_failure_returns_details', 1, 8, 4).
python_method('TestBuildFailures', 'test_mobile_build_failure_returns_details', 1, 4, 3).
python_method('TestBuildFailures', 'test_web_build_failure_returns_details', 1, 4, 3).
python_method('TestBuildFailures', 'test_build_with_stderr_captured', 1, 3, 4).
python_class('tests/test_e2e_build_extended.py', 'TestServiceConfigBuildTargets').
python_method('TestServiceConfigBuildTargets', 'test_desktop_electron_from_service_config', 0, 4, 1).
python_method('TestServiceConfigBuildTargets', 'test_mobile_capacitor_from_service_config', 0, 4, 1).
python_method('TestServiceConfigBuildTargets', 'test_mobile_kivy_from_service_config', 0, 4, 1).
python_method('TestServiceConfigBuildTargets', 'test_desktop_pyqt_from_service_config', 0, 4, 1).
python_class('tests/test_e2e_build_extended.py', 'TestE2EPythonApiToElectronDesktop').
python_method('TestE2EPythonApiToElectronDesktop', 'test_parse_python_api_as_electron', 1, 11, 3).
python_method('TestE2EPythonApiToElectronDesktop', 'test_scaffold_with_python_deps_package_json', 1, 5, 8).
python_method('TestE2EPythonApiToElectronDesktop', 'test_full_build_succeeds', 1, 7, 9).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployElectron').
python_method('TestE2EDeployElectron', 'test_headless_deploys_via_http', 4, 3, 2).
python_method('TestE2EDeployElectron', 'test_headless_serves_correct_port', 4, 2, 1).
python_method('TestE2EDeployElectron', 'test_scaffold_creates_electron_files', 1, 6, 9).
python_method('TestE2EDeployElectron', 'test_native_with_display', 3, 2, 4).
python_method('TestE2EDeployElectron', 'test_index_html_written_to_sandbox', 4, 3, 4).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployPyQt').
python_method('TestE2EDeployPyQt', 'test_headless_deploys_via_http', 4, 3, 1).
python_method('TestE2EDeployPyQt', 'test_scaffold_creates_spec', 1, 2, 4).
python_method('TestE2EDeployPyQt', 'test_native_with_display', 3, 2, 3).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployTauri').
python_method('TestE2EDeployTauri', 'test_headless_deploys_via_http', 4, 3, 2).
python_method('TestE2EDeployTauri', 'test_scaffold_creates_tauri_config', 1, 3, 6).
python_method('TestE2EDeployTauri', 'test_native_with_display', 3, 2, 4).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployCapacitor').
python_method('TestE2EDeployCapacitor', 'test_headless_deploys_via_http', 4, 3, 3).
python_method('TestE2EDeployCapacitor', 'test_serves_from_www_dir', 4, 2, 1).
python_method('TestE2EDeployCapacitor', 'test_scaffold_creates_capacitor_config', 1, 8, 9).
python_method('TestE2EDeployCapacitor', 'test_native_with_display', 3, 2, 4).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployKivy').
python_method('TestE2EDeployKivy', 'test_headless_deploys_via_http', 4, 3, 1).
python_method('TestE2EDeployKivy', 'test_scaffold_creates_buildozer_spec', 1, 4, 5).
python_method('TestE2EDeployKivy', 'test_native_with_display', 3, 2, 3).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDeployReactNative').
python_method('TestE2EDeployReactNative', 'test_headless_deploys_via_http', 4, 3, 2).
python_method('TestE2EDeployReactNative', 'test_native_with_display', 3, 2, 4).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EWebServiceNotAffected').
python_method('TestE2EWebServiceNotAffected', 'test_fastapi_runs_normally_on_headless', 4, 4, 2).
python_method('TestE2EWebServiceNotAffected', 'test_express_runs_normally_on_headless', 4, 3, 1).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EAssetDiscovery').
python_method('TestE2EAssetDiscovery', 'test_capacitor_www_dir', 1, 2, 3).
python_method('TestE2EAssetDiscovery', 'test_react_build_dir', 1, 2, 3).
python_method('TestE2EAssetDiscovery', 'test_vite_dist_dir', 1, 2, 3).
python_method('TestE2EAssetDiscovery', 'test_public_dir', 1, 2, 3).
python_method('TestE2EAssetDiscovery', 'test_root_fallback', 1, 2, 2).
python_method('TestE2EAssetDiscovery', 'test_no_index_falls_back_to_root', 1, 2, 1).
python_method('TestE2EAssetDiscovery', 'test_priority_www_over_dist', 1, 3, 3).
python_method('TestE2EAssetDiscovery', 'test_priority_dist_over_build', 1, 3, 3).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EPreviewCommandGeneration').
python_method('TestE2EPreviewCommandGeneration', 'test_python_fallback_includes_bind', 2, 5, 3).
python_method('TestE2EPreviewCommandGeneration', 'test_npx_serve_with_spa_flag', 2, 4, 3).
python_method('TestE2EPreviewCommandGeneration', 'test_serves_subdir_when_index_in_www', 2, 4, 4).
python_method('TestE2EPreviewCommandGeneration', 'test_venv_python_preferred', 2, 3, 4).
python_method('TestE2EPreviewCommandGeneration', 'test_creates_fallback_html_for_python_desktop', 2, 6, 5).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2EDetectionPerFramework').
python_method('TestE2EDetectionPerFramework', '_no_display', 1, 1, 3).
python_method('TestE2EDetectionPerFramework', 'test_electron_dot', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_npx_electron', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_cap_run', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_cap_open', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_tauri_dev', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_flutter_run', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_react_native_run', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_python_main_with_kivy_target', 0, 2, 3).
python_method('TestE2EDetectionPerFramework', 'test_python_main_with_pyqt_target', 0, 2, 3).
python_method('TestE2EDetectionPerFramework', 'test_python_main_with_pyinstaller_target', 0, 2, 3).
python_method('TestE2EDetectionPerFramework', 'test_python_main_with_tkinter_target', 0, 2, 3).
python_method('TestE2EDetectionPerFramework', 'test_python_main_without_target_not_affected', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_uvicorn_not_affected', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_node_not_affected', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_display_set_skips_preview', 0, 2, 2).
python_method('TestE2EDetectionPerFramework', 'test_xvfb_available_skips_preview', 1, 3, 3).
python_method('TestE2EDetectionPerFramework', 'test_target_cfg_framework_triggers_preview', 0, 2, 3).
python_method('TestE2EDetectionPerFramework', 'test_web_target_not_affected', 0, 2, 3).
python_class('tests/test_e2e_deploy_desktop_mobile.py', 'TestE2ESystemDeps').
python_method('TestE2ESystemDeps', 'test_framework_system_deps_registry_has_tkinter', 0, 3, 0).
python_method('TestE2ESystemDeps', 'test_framework_system_deps_registry_has_electron', 0, 3, 1).
python_method('TestE2ESystemDeps', 'test_framework_system_deps_registry_has_kivy', 0, 3, 1).
python_method('TestE2ESystemDeps', 'test_import_to_apt_maps_tkinter', 0, 3, 0).
python_method('TestE2ESystemDeps', 'test_install_system_deps_skips_unknown_framework', 1, 2, 3).
python_method('TestE2ESystemDeps', 'test_install_system_deps_skips_when_all_installed', 1, 2, 6).
python_method('TestE2ESystemDeps', 'test_install_system_deps_calls_apt_when_missing', 1, 3, 5).
python_method('TestE2ESystemDeps', 'test_install_system_deps_nonfatal_on_apt_missing', 1, 2, 6).
python_class('tests/test_electron_xvfb.py', 'TestDetectWebPreviewNeeded').
python_method('TestDetectWebPreviewNeeded', 'test_electron_cmd_no_display_no_xvfb', 1, 2, 4).
python_method('TestDetectWebPreviewNeeded', 'test_electron_cmd_with_display', 1, 2, 3).
python_method('TestDetectWebPreviewNeeded', 'test_electron_cmd_with_xvfb', 1, 3, 4).
python_method('TestDetectWebPreviewNeeded', 'test_capacitor_cmd_headless', 1, 2, 4).
python_method('TestDetectWebPreviewNeeded', 'test_web_cmd_not_affected', 1, 2, 4).
python_method('TestDetectWebPreviewNeeded', 'test_python_main_only_native_with_target', 1, 2, 4).
python_method('TestDetectWebPreviewNeeded', 'test_python_main_native_with_desktop_target', 1, 2, 5).
python_class('tests/test_electron_xvfb.py', 'TestFindWebAssetsDir').
python_method('TestFindWebAssetsDir', 'test_index_at_root', 1, 2, 2).
python_method('TestFindWebAssetsDir', 'test_www_subdir', 1, 2, 3).
python_method('TestFindWebAssetsDir', 'test_dist_subdir', 1, 2, 3).
python_method('TestFindWebAssetsDir', 'test_fallback_to_root', 1, 2, 1).
python_method('TestFindWebAssetsDir', 'test_www_preferred_over_dist', 1, 3, 3).
python_class('tests/test_electron_xvfb.py', 'TestBuildWebPreviewCmd').
python_method('TestBuildWebPreviewCmd', 'test_fallback_to_python_http_server', 2, 6, 4).
python_method('TestBuildWebPreviewCmd', 'test_uses_npx_serve_when_available', 2, 4, 4).
python_class('tests/test_electron_xvfb.py', 'TestWebPreviewIntegration').
python_method('TestWebPreviewIntegration', 'test_electron_uses_web_preview_on_headless', 4, 5, 5).
python_method('TestWebPreviewIntegration', 'test_electron_runs_natively_with_display', 4, 3, 5).
python_class('tests/test_llm.py', 'TestLLMStatus').
python_method('TestLLMStatus', 'test_llm_status_without_lolm', 0, 4, 3).
python_method('TestLLMStatus', 'test_llm_status_with_providers', 0, 5, 3).
python_method('TestLLMStatus', 'test_llm_status_no_providers_available', 0, 3, 3).
python_class('tests/test_llm.py', 'TestLLMPriority').
python_method('TestLLMPriority', 'test_llm_priority_set_success', 0, 3, 4).
python_method('TestLLMPriority', 'test_llm_priority_set_failure', 0, 3, 3).
python_method('TestLLMPriority', 'test_llm_priority_without_lolm', 0, 3, 3).
python_class('tests/test_llm.py', 'TestLLMReset').
python_method('TestLLMReset', 'test_llm_reset_success', 0, 3, 4).
python_method('TestLLMReset', 'test_llm_reset_failure', 0, 3, 3).
python_class('tests/test_llm.py', 'TestLLMTest').
python_method('TestLLMTest', 'test_llm_test_basic', 0, 3, 4).
python_method('TestLLMTest', 'test_llm_test_with_rotation', 0, 2, 5).
python_method('TestLLMTest', 'test_llm_test_with_provider', 0, 3, 5).
python_method('TestLLMTest', 'test_llm_test_error', 0, 4, 5).
python_class('tests/test_llm.py', 'TestLLMDoctor').
python_method('TestLLMDoctor', 'test_llm_doctor_outputs_environment_info', 0, 8, 3).
python_class('tests/test_llm.py', 'TestLLMModule').
python_method('TestLLMModule', 'test_is_lolm_available_false', 0, 2, 2).
python_method('TestLLMModule', 'test_get_llm_status_without_lolm', 0, 5, 2).
python_class('tests/test_llm.py', 'TestPactownLLMClass').
python_method('TestPactownLLMClass', 'test_pactown_llm_singleton', 0, 2, 3).
python_method('TestPactownLLMClass', 'test_pactown_llm_generate_with_rotation', 0, 2, 5).
python_class('tests/test_node_cache.py', 'TestHashStability').
python_method('TestHashStability', 'test_same_deps_same_hash', 0, 2, 3).
python_method('TestHashStability', 'test_different_deps_different_hash', 0, 2, 3).
python_method('TestHashStability', 'test_order_independent', 0, 2, 3).
python_method('TestHashStability', 'test_description_change_does_not_bust_cache', 0, 2, 3).
python_method('TestHashStability', 'test_scripts_change_does_not_bust_cache', 0, 2, 3).
python_method('TestHashStability', 'test_name_change_busts_cache', 0, 2, 3).
python_method('TestHashStability', 'test_invalid_json_returns_stable_hash', 0, 3, 3).
python_class('tests/test_node_cache.py', 'TestSaveRestore').
python_method('TestSaveRestore', 'test_save_and_restore', 1, 8, 11).
python_method('TestSaveRestore', 'test_cache_miss_returns_false', 1, 2, 4).
python_method('TestSaveRestore', 'test_save_without_node_modules_returns_none', 1, 2, 4).
python_method('TestSaveRestore', 'test_restore_overwrites_existing_node_modules', 1, 4, 9).
python_class('tests/test_node_cache.py', 'TestPersistence').
python_method('TestPersistence', 'test_new_instance_loads_existing_cache', 1, 3, 8).
python_class('tests/test_node_cache.py', 'TestInvalidation').
python_method('TestInvalidation', 'test_invalidate_removes_entry', 1, 3, 8).
python_method('TestInvalidation', 'test_invalidate_nonexistent_is_noop', 1, 1, 3).
python_class('tests/test_node_cache.py', 'TestEviction').
python_method('TestEviction', 'test_max_entries_evicts_lru', 1, 5, 10).
python_class('tests/test_node_cache.py', 'TestStats').
python_method('TestStats', 'test_get_stats_empty', 1, 4, 2).
python_method('TestStats', 'test_get_stats_with_entries', 1, 4, 8).
python_class('tests/test_node_cache.py', 'TestOnLog').
python_method('TestOnLog', 'test_save_sends_log', 1, 2, 8).
python_method('TestOnLog', 'test_restore_sends_log', 1, 2, 9).
python_class('tests/test_node_cache.py', 'TestSortedDeps').
python_method('TestSortedDeps', 'test_sorts_dict', 0, 2, 1).
python_method('TestSortedDeps', 'test_non_dict_returns_empty', 0, 4, 1).
python_method('TestSortedDeps', 'test_empty_dict', 0, 2, 1).
python_class('tests/test_quadlet_security.py', 'TestContainerNameInjection').
python_method('TestContainerNameInjection', 'test_container_name_sanitization', 0, 10, 4).
python_method('TestContainerNameInjection', 'test_filename_sanitization', 0, 4, 1).
python_class('tests/test_quadlet_security.py', 'TestEnvironmentVariableInjection').
python_method('TestEnvironmentVariableInjection', 'test_env_value_sanitization', 0, 8, 7).
python_method('TestEnvironmentVariableInjection', 'test_env_key_sanitization', 0, 2, 3).
python_class('tests/test_quadlet_security.py', 'TestVolumeMountInjection').
python_method('TestVolumeMountInjection', 'test_volume_path_validation', 0, 11, 3).
python_method('TestVolumeMountInjection', 'test_volume_options_injection', 0, 9, 6).
python_class('tests/test_quadlet_security.py', 'TestTraefikLabelInjection').
python_method('TestTraefikLabelInjection', 'test_domain_injection', 0, 8, 3).
python_method('TestTraefikLabelInjection', 'test_middleware_injection', 0, 3, 3).
python_class('tests/test_quadlet_security.py', 'TestSystemdUnitInjection').
python_method('TestSystemdUnitInjection', 'test_section_injection', 0, 5, 5).
python_method('TestSystemdUnitInjection', 'test_directive_injection', 0, 4, 5).
python_class('tests/test_quadlet_security.py', 'TestTenantIsolation').
python_method('TestTenantIsolation', 'test_tenant_path_traversal', 0, 7, 4).
python_method('TestTenantIsolation', 'test_tenant_network_isolation', 0, 2, 2).
python_class('tests/test_quadlet_security.py', 'TestCommandInjection').
python_method('TestCommandInjection', 'test_health_check_injection', 0, 7, 3).
python_method('TestCommandInjection', 'test_image_name_injection', 0, 6, 5).
python_class('tests/test_quadlet_security.py', 'TestAPISecurityInjection').
python_method('TestAPISecurityInjection', 'api_client', 0, 1, 2).
python_method('TestAPISecurityInjection', 'test_markdown_content_injection', 1, 5, 3).
python_method('TestAPISecurityInjection', 'test_tenant_id_injection', 1, 4, 3).
python_class('tests/test_quadlet_security.py', 'TestSecurityHardening').
python_method('TestSecurityHardening', 'test_no_new_privileges', 0, 2, 3).
python_method('TestSecurityHardening', 'test_capability_drop', 0, 2, 3).
python_method('TestSecurityHardening', 'test_resource_limits', 0, 3, 3).
python_method('TestSecurityHardening', 'test_read_only_filesystem', 0, 2, 3).
python_class('tests/test_quadlet_security.py', 'TestInputSanitization').
python_method('TestInputSanitization', 'test_sanitize_name', 0, 4, 2).
python_class('tests/test_security.py', 'TestInputSanitization').
python_method('TestInputSanitization', 'test_service_name_rejects_path_traversal', 0, 9, 1).
python_method('TestInputSanitization', 'test_tenant_id_sanitization', 0, 7, 3).
python_class('tests/test_security.py', 'TestPathTraversal').
python_method('TestPathTraversal', 'test_sandbox_path_stays_within_root', 0, 4, 7).
python_class('tests/test_security.py', 'TestCommandInjection').
python_method('TestCommandInjection', 'test_quadlet_sanitize_name', 0, 8, 1).
python_method('TestCommandInjection', 'test_env_value_no_newlines', 0, 4, 1).
python_class('tests/test_security.py', 'TestSecretsLeakage').
python_method('TestSecretsLeakage', 'test_config_env_handling', 0, 3, 1).
python_method('TestSecretsLeakage', 'test_error_messages_do_not_leak_secrets', 0, 5, 6).
python_class('tests/test_security.py', 'TestNetworkSecurity').
python_method('TestNetworkSecurity', 'test_port_allocation_within_range', 0, 2, 1).
python_method('TestNetworkSecurity', 'test_service_endpoint_creation', 0, 4, 1).
python_class('tests/test_security.py', 'TestAuthorizationChecks').
python_method('TestAuthorizationChecks', 'test_security_policy_user_profile', 0, 2, 4).
python_method('TestAuthorizationChecks', 'test_service_runner_creates_sandbox', 0, 2, 3).
python_class('tests/test_security.py', 'TestRateLimiting').
python_method('TestRateLimiting', 'test_rate_limiter_exists', 0, 2, 2).
python_method('TestRateLimiting', 'test_api_rate_limit_headers', 0, 3, 2).
python_class('tests/test_security.py', 'TestCryptography').
python_method('TestCryptography', 'test_no_weak_random', 0, 6, 7).
python_class('tests/test_security.py', 'TestDependencySecurity').
python_method('TestDependencySecurity', 'test_no_known_vulnerabilities', 0, 3, 5).
python_class('tools/validate_artifacts_docker.py', 'ValidationResult').
python_class('tools/validate_artifacts_docker.py', 'ValidationReport').
python_method('ValidationReport', 'total', 0, 1, 1).
python_method('ValidationReport', 'passed', 0, 3, 1).
python_method('ValidationReport', 'failed', 0, 3, 1).
python_method('ValidationReport', 'print_summary', 0, 12, 5).

% ── Dependencies ─────────────────────────────────────────
project_dependency('pytest>=7.0', 'requirements-dev.txt').
project_dependency('pytest-asyncio==0.23.4', 'requirements-dev.txt').

% ── Makefile Targets ─────────────────────────────────────
makefile_target('BUMP2VERSION_PY', '').
makefile_target('BUMP2VERSION', '').
makefile_target('BUMP2VERSION', '').
makefile_target('help', '').
makefile_target('install', '').
makefile_target('dev', '').
makefile_target('ensure-test-deps', '').
makefile_target('test', '').
makefile_target('test-api', '').
makefile_target('test-fast', '').
makefile_target('test-full', '').
makefile_target('test-cov', '').
makefile_target('lint', '').
makefile_target('format', '').
makefile_target('build', '').
makefile_target('clean', '').
makefile_target('registry', 'Registry commands').
makefile_target('registry-bg', '').
makefile_target('up', 'Ecosystem commands').
makefile_target('down', '').
makefile_target('status', '').
makefile_target('validate', '').
makefile_target('graph', '').
makefile_target('examples', 'Development helpers').
makefile_target('init', '').
makefile_target('publish', '').
makefile_target('pull', '').
makefile_target('check-pypi-deps', '').
makefile_target('publish-pypi', '').
makefile_target('version', 'Version management').
makefile_target('bump-patch', '').
makefile_target('bump-minor', '').
makefile_target('bump-major', '').
makefile_target('release', '').
makefile_target('sync-pactown-com', '').
makefile_target('security', 'Security targets').
makefile_target('security-sast', '').
makefile_target('security-deps', '').
makefile_target('security-secrets', '').
makefile_target('security-all', '').
makefile_target('ARTIFACT_ROOT', 'Artifact generation & validation').
makefile_target('ARTIFACT_TESTS', '').
makefile_target('artifacts-docker', '').
makefile_target('artifacts-clean', '').
makefile_target('CROSS_PLATFORM_TESTS', '').
makefile_target('artifacts-quick', '').
makefile_target('artifacts', '').

% ── Taskfile Tasks ───────────────────────────────────────

% ── Environment Variables ────────────────────────────────
env_variable('OPENROUTER_API_KEY', '*(not set)*', 'Required: OpenRouter API key (https://openrouter.ai/keys)').
env_variable('LLM_MODEL', 'openrouter/qwen/qwen3-coder-next', 'Model (default: openrouter/qwen/qwen3-coder-next)').
env_variable('PFIX_AUTO_APPLY', 'true', 'true = apply fixes without asking').
env_variable('PFIX_AUTO_INSTALL_DEPS', 'true', 'true = auto pip/uv install').
env_variable('PFIX_AUTO_RESTART', 'false', 'true = os.execv restart after fix').
env_variable('PFIX_MAX_RETRIES', '3', '').
env_variable('PFIX_DRY_RUN', 'false', '').
env_variable('PFIX_ENABLED', 'true', '').
env_variable('PFIX_GIT_COMMIT', 'false', 'true = auto-commit fixes').
env_variable('PFIX_GIT_PREFIX', 'pfix:', 'commit message prefix').
env_variable('PFIX_CREATE_BACKUPS', 'false', 'false = disable .pfix_backups/ directory').

% ── TestQL Scenarios ─────────────────────────────────────
testql_scenario('generated-api-integration.testql.toon.yaml', 'api').
testql_scenario('generated-api-smoke.testql.toon.yaml', 'api').
testql_scenario('generated-from-pytests.testql.toon.yaml', 'integration').

% ── Semantic Facts from SUMD.md ──────────────────────────
```

## Call Graph

*181 nodes · 160 edges · 37 modules · CC̄=4.5*

### Hubs (by degree)

| Function | CC | in | out | total |
|----------|----|----|-----|-------|
| `start_service` *(in src.pactown.sandbox_manager.SandboxManager)* | 53 ⚠ | 0 | 145 | **145** |
| `create_quadlet_api` *(in src.pactown.deploy.quadlet_api)* | 1 | 1 | 114 | **115** |
| `create_runner_api` *(in src.pactown.runner_api)* | 1 | 1 | 113 | **114** |
| `log` *(in src.pactown.security.AnomalyLogger)* | 6 | 87 | 13 | **100** |
| `fast_run` *(in src.pactown.service_runner.ServiceRunner)* | 36 ⚠ | 0 | 88 | **88** |
| `build_service` *(in src.pactown.sandbox_manager.SandboxManager)* | 40 ⚠ | 0 | 76 | **76** |
| `run_from_content` *(in src.pactown.service_runner.ServiceRunner)* | 37 ⚠ | 0 | 74 | **74** |
| `fast_create_sandbox` *(in src.pactown.fast_start.FastServiceStarter)* | 20 ⚠ | 0 | 63 | **63** |

```toon markpact:analysis path=project/calls.toon.yaml
# code2llm call graph | /home/tom/github/wronai/pactown
# generated in 0.09s
# nodes: 181 | edges: 160 | modules: 37
# CC̄=4.5

HUBS[20]:
  src.pactown.sandbox_manager.SandboxManager.start_service
    CC=53  in:0  out:145  total:145
  src.pactown.deploy.quadlet_api.create_quadlet_api
    CC=1  in:1  out:114  total:115
  src.pactown.runner_api.create_runner_api
    CC=1  in:1  out:113  total:114
  src.pactown.security.AnomalyLogger.log
    CC=6  in:87  out:13  total:100
  src.pactown.service_runner.ServiceRunner.fast_run
    CC=36  in:0  out:88  total:88
  src.pactown.sandbox_manager.SandboxManager.build_service
    CC=40  in:0  out:76  total:76
  src.pactown.service_runner.ServiceRunner.run_from_content
    CC=37  in:0  out:74  total:74
  src.pactown.fast_start.FastServiceStarter.fast_create_sandbox
    CC=20  in:0  out:63  total:63
  src.pactown.registry.server.create_app
    CC=1  in:1  out:52  total:53
  src.pactown.error_context.build_error_context
    CC=41  in:3  out:47  total:50
  src.pactown.cli.llm_status
    CC=18  in:0  out:45  total:45
  src.pactown.cli.build
    CC=14  in:0  out:43  total:43
  tools.validate_artifacts_docker.main
    CC=17  in:0  out:42  total:42
  src.pactown.builders.desktop.DesktopBuilder.build_parallel
    CC=18  in:0  out:37  total:37
  src.pactown.registry.models.RegistryStorage.list
    CC=4  in:33  out:3  total:36
  src.pactown.fast_start.DependencyCache.create_and_cache
    CC=6  in:0  out:33  total:33
  src.pactown.cli.deploy
    CC=7  in:0  out:30  total:30
  tools.sync_pactown_com_dependency.main
    CC=8  in:0  out:29  total:29
  src.pactown.cli.up
    CC=9  in:0  out:27  total:27
  src.pactown.parallel.run_parallel
    CC=8  in:2  out:24  total:26

MODULES:
  src.pactown.builders.base  [1 funcs]
    _log  CC=3  out:1
  src.pactown.builders.desktop  [4 funcs]
    _generate_linux_launcher  CC=3  out:8
    _move_to_dev_deps  CC=4  out:5
    build  CC=11  out:22
    build_parallel  CC=18  out:37
  src.pactown.builders.mobile  [3 funcs]
    _scaffold_kivy  CC=8  out:8
    build  CC=10  out:21
    _sanitize_java_package_id  CC=5  out:7
  src.pactown.builders.registry  [2 funcs]
    get_builder  CC=2  out:2
    get_builder_for_target  CC=2  out:1
  src.pactown.builders.web  [1 funcs]
    build  CC=4  out:11
  src.pactown.cli  [27 funcs]
    build  CC=14  out:43
    cli  CC=1  out:2
    deploy  CC=7  out:30
    down  CC=2  out:10
    generate  CC=2  out:20
    get_llm  CC=1  out:1
    get_llm_status  CC=1  out:1
    graph  CC=2  out:10
    is_lolm_available  CC=1  out:1
    llm_priority  CC=3  out:8
  src.pactown.config  [1 funcs]
    load_config  CC=2  out:4
  src.pactown.deploy.ansible  [9 funcs]
    _write_inventory  CC=1  out:4
    build_image  CC=3  out:6
    deploy  CC=3  out:5
    stop  CC=2  out:4
    write_all  CC=1  out:5
    generate_build_playbook  CC=2  out:0
    generate_deploy_playbook  CC=10  out:4
    generate_inventory  CC=5  out:0
    generate_teardown_playbook  CC=1  out:0
  src.pactown.deploy.compose  [1 funcs]
    generate_compose_from_config  CC=4  out:23
  src.pactown.deploy.quadlet  [10 funcs]
    container  CC=18  out:22
    generate_markdown_service_quadlet  CC=3  out:4
    generate_traefik_quadlet  CC=1  out:4
    sanitize_domain  CC=3  out:5
    sanitize_env_key  CC=4  out:5
    sanitize_env_value  CC=2  out:4
    sanitize_image  CC=3  out:5
    sanitize_name  CC=5  out:9
    sanitize_path  CC=3  out:4
    validate_volume  CC=7  out:2
  src.pactown.deploy.quadlet_api  [2 funcs]
    create_quadlet_api  CC=1  out:114
    run_api  CC=1  out:2
  src.pactown.deploy.quadlet_shell  [5 funcs]
    do_deploy  CC=7  out:20
    do_generate  CC=7  out:18
    do_generate_traefik  CC=4  out:10
    do_init  CC=3  out:14
    run_shell  CC=2  out:3
  src.pactown.error_context  [5 funcs]
    _truncate_text  CC=4  out:1
    build_error_context  CC=41  out:47
    extract_file_paths  CC=9  out:8
    extract_trace_ids  CC=6  out:6
    most_probable_file  CC=7  out:7
  src.pactown.events  [8 funcs]
    get_all  CC=1  out:2
    get_event_store  CC=2  out:1
    get_project_commands  CC=2  out:2
    get_project_queries  CC=2  out:2
    get_security_commands  CC=2  out:2
    get_security_queries  CC=2  out:2
    get_service_commands  CC=2  out:2
    get_service_queries  CC=2  out:2
  src.pactown.fast_start  [6 funcs]
    create_and_cache  CC=6  out:33
    _install_deps_direct  CC=2  out:7
    _write_files_parallel  CC=1  out:6
    fast_create_sandbox  CC=20  out:63
    run_parallel  CC=2  out:5
    _run_streamed  CC=10  out:7
  src.pactown.generator  [4 funcs]
    generate_config  CC=9  out:11
    print_scan_results  CC=5  out:14
    scan_folder  CC=5  out:8
    scan_readme  CC=12  out:12
  src.pactown.iac  [7 funcs]
    _default_base_image  CC=2  out:0
    _runtime_type  CC=2  out:0
    build_sandbox_spec  CC=17  out:21
    build_single_service_compose  CC=8  out:4
    write_sandbox_iac  CC=5  out:9
    write_sandbox_manifest  CC=1  out:2
    write_single_service_compose  CC=1  out:2
  src.pactown.llm  [5 funcs]
    generate  CC=2  out:3
    get_llm  CC=1  out:1
    get_llm_status  CC=3  out:7
    reset_provider  CC=3  out:4
    set_provider_priority  CC=3  out:4
  src.pactown.markpact_blocks  [2 funcs]
    extract_run_command  CC=17  out:4
    extract_target_config  CC=3  out:1
  src.pactown.network  [1 funcs]
    list_services  CC=1  out:2
  src.pactown.node_cache  [5 funcs]
    _hash_pkg  CC=2  out:10
    restore  CC=4  out:5
    save  CC=5  out:13
    _copytree_hardlink  CC=3  out:4
    _sorted_deps  CC=2  out:4
  src.pactown.orchestrator  [1 funcs]
    from_file  CC=1  out:3
  src.pactown.parallel  [3 funcs]
    build_sandboxes  CC=2  out:2
    run_in_dependency_waves  CC=12  out:14
    run_parallel  CC=8  out:24
  src.pactown.platform  [15 funcs]
    _normalize_domain  CC=2  out:2
    _normalize_separator  CC=1  out:2
    api_base_url  CC=2  out:5
    build_origin  CC=2  out:2
    build_project_host  CC=1  out:2
    build_project_subdomain  CC=1  out:5
    build_service_subdomain  CC=2  out:6
    coerce_subdomain_separator  CC=2  out:0
    is_local_domain  CC=1  out:1
    normalize_domain  CC=2  out:3
  src.pactown.registry.models  [1 funcs]
    list  CC=4  out:3
  src.pactown.registry.server  [2 funcs]
    create_app  CC=1  out:52
    main  CC=1  out:7
  src.pactown.resolver  [2 funcs]
    get_shutdown_order  CC=1  out:3
    print_graph  CC=6  out:7
  src.pactown.runner_api  [14 funcs]
    _resolve_service_id  CC=3  out:8
    _sandbox_path_for  CC=1  out:2
    delete_sandbox_file  CC=4  out:9
    prepare_sandbox  CC=4  out:11
    read_sandbox_file  CC=5  out:10
    write_sandbox_file  CC=1  out:6
    _dns_label  CC=1  out:1
    _resolve_in_dir  CC=2  out:4
    _service_name_for  CC=1  out:1
    _validate_rel_path  CC=5  out:7
  src.pactown.runner_types  [1 funcs]
    kill_process_on_port  CC=25  out:18
  src.pactown.sandbox_helpers  [8 funcs]
    _call_on_log  CC=6  out:7
    _escape_dotenv_value  CC=1  out:5
    _filter_runtime_env  CC=9  out:7
    _heartbeat  CC=4  out:6
    _sanitize_inherited_env  CC=16  out:18
    _should_emit_to_ui  CC=2  out:5
    _ui_log_level  CC=7  out:4
    _write_dotenv_file  CC=8  out:9
  src.pactown.sandbox_manager  [7 funcs]
    build_service  CC=40  out:76
    start_service  CC=53  out:145
    stop_all  CC=2  out:3
    _build_web_preview_cmd  CC=14  out:25
    _find_web_assets_dir  CC=5  out:3
    _inject_electron_web_polyfill  CC=18  out:12
    _install_system_deps  CC=11  out:18
  src.pactown.security  [2 funcs]
    log  CC=6  out:13
    get_security_policy  CC=2  out:1
  src.pactown.service_runner  [5 funcs]
    __init__  CC=5  out:9
    _prune_stale_user_services  CC=14  out:9
    fast_run  CC=36  out:88
    run_from_content  CC=37  out:74
    stop_all  CC=2  out:3
  src.pactown.targets  [1 funcs]
    list_frameworks  CC=4  out:3
  src.pactown.user_isolation  [2 funcs]
    get_user_stats  CC=5  out:11
    list_users  CC=1  out:2
  tools.sync_pactown_com_dependency  [3 funcs]
    _read_pactown_version  CC=2  out:5
    _update_requirements_pin  CC=8  out:11
    main  CC=8  out:29
  tools.validate_artifacts_docker  [5 funcs]
    _find_service_dir  CC=1  out:1
    collect_artifacts  CC=6  out:8
    docker_run  CC=6  out:4
    main  CC=17  out:42
    validate_artifact  CC=6  out:21

EDGES:
  src.pactown.sandbox_helpers._should_emit_to_ui → src.pactown.sandbox_helpers._ui_log_level
  src.pactown.sandbox_helpers._call_on_log → src.pactown.registry.models.RegistryStorage.list
  src.pactown.sandbox_helpers._sanitize_inherited_env → src.pactown.registry.models.RegistryStorage.list
  src.pactown.sandbox_helpers._write_dotenv_file → src.pactown.sandbox_helpers._escape_dotenv_value
  src.pactown.sandbox_helpers._heartbeat → src.pactown.sandbox_helpers._should_emit_to_ui
  src.pactown.sandbox_helpers._heartbeat → src.pactown.sandbox_helpers._call_on_log
  src.pactown.markpact_blocks.extract_run_command → src.pactown.markpact_blocks.extract_target_config
  src.pactown.error_context.build_error_context → src.pactown.error_context._truncate_text
  src.pactown.error_context.build_error_context → src.pactown.error_context.extract_trace_ids
  src.pactown.error_context.build_error_context → src.pactown.error_context.extract_file_paths
  src.pactown.error_context.build_error_context → src.pactown.error_context.most_probable_file
  src.pactown.generator.scan_folder → src.pactown.registry.models.RegistryStorage.list
  src.pactown.generator.scan_folder → src.pactown.generator.scan_readme
  src.pactown.generator.generate_config → src.pactown.generator.scan_folder
  src.pactown.generator.print_scan_results → src.pactown.generator.scan_folder
  src.pactown.iac.build_sandbox_spec → src.pactown.iac._runtime_type
  src.pactown.iac.write_sandbox_iac → src.pactown.iac.build_single_service_compose
  src.pactown.iac.write_sandbox_iac → src.pactown.iac.write_single_service_compose
  src.pactown.iac.write_sandbox_iac → src.pactown.iac.build_sandbox_spec
  src.pactown.iac.write_sandbox_iac → src.pactown.iac.write_sandbox_manifest
  src.pactown.iac.write_sandbox_iac → src.pactown.iac._default_base_image
  src.pactown.user_isolation.UserIsolationManager.list_users → src.pactown.registry.models.RegistryStorage.list
  src.pactown.user_isolation.UserIsolationManager.get_user_stats → src.pactown.registry.models.RegistryStorage.list
  src.pactown.service_runner.ServiceRunner.__init__ → src.pactown.security.get_security_policy
  src.pactown.service_runner.ServiceRunner._prune_stale_user_services → src.pactown.registry.models.RegistryStorage.list
  src.pactown.service_runner.ServiceRunner.run_from_content → src.pactown.runner_types.kill_process_on_port
  src.pactown.service_runner.ServiceRunner.run_from_content → src.pactown.security.AnomalyLogger.log
  src.pactown.service_runner.ServiceRunner.run_from_content → src.pactown.sandbox_helpers._sanitize_inherited_env
  src.pactown.service_runner.ServiceRunner.stop_all → src.pactown.registry.models.RegistryStorage.list
  src.pactown.service_runner.ServiceRunner.fast_run → src.pactown.runner_types.kill_process_on_port
  src.pactown.service_runner.ServiceRunner.fast_run → src.pactown.markpact_blocks.extract_run_command
  src.pactown.service_runner.ServiceRunner.fast_run → src.pactown.sandbox_helpers._filter_runtime_env
  src.pactown.service_runner.ServiceRunner.fast_run → src.pactown.sandbox_helpers._sanitize_inherited_env
  src.pactown.targets.list_frameworks → src.pactown.registry.models.RegistryStorage.list
  src.pactown.builders.registry.get_builder_for_target → src.pactown.builders.registry.get_builder
  src.pactown.builders.web.WebBuilder.build → src.pactown.builders.base.Builder._log
  src.pactown.builders.mobile.MobileBuilder.build → src.pactown.builders.base.Builder._log
  src.pactown.builders.mobile.MobileBuilder._scaffold_kivy → src.pactown.builders.mobile._sanitize_java_package_id
  src.pactown.resolver.DependencyResolver.get_shutdown_order → src.pactown.registry.models.RegistryStorage.list
  src.pactown.resolver.DependencyResolver.print_graph → src.pactown.registry.models.RegistryStorage.list
  src.pactown.parallel.run_in_dependency_waves → src.pactown.parallel.run_parallel
  src.pactown.parallel.ParallelSandboxBuilder.build_sandboxes → src.pactown.parallel.run_parallel
  src.pactown.builders.desktop.DesktopBuilder.build → src.pactown.builders.base.Builder._log
  src.pactown.builders.desktop.DesktopBuilder._move_to_dev_deps → src.pactown.registry.models.RegistryStorage.list
  src.pactown.builders.desktop.DesktopBuilder.build_parallel → src.pactown.builders.base.Builder._log
  src.pactown.builders.desktop.DesktopBuilder._generate_linux_launcher → src.pactown.registry.models.RegistryStorage.list
  src.pactown.node_cache.NodeModulesCache.restore → src.pactown.node_cache._copytree_hardlink
  src.pactown.node_cache.NodeModulesCache.save → src.pactown.node_cache._copytree_hardlink
  src.pactown.node_cache.NodeModulesCache._hash_pkg → src.pactown.node_cache._sorted_deps
  src.pactown.llm.generate → src.pactown.llm.get_llm
```

## Test Contracts

*Scenarios as contract signatures — what the system guarantees.*

### Api (2)

**`API Integration Tests`**
- `GET /health` → `200`
- `GET /api/v1/status` → `200`
- `POST /api/v1/test` → `201`
- assert `status == ok`
- assert `response_time < 1000`

**`Auto-generated API Smoke Tests`**
- assert `_status < 500`
- assert `_status >= 200`
- detectors: FastAPIDetector, FlaskDetector, ExpressDetector, ConfigEndpointDetector

### Integration (1)

**`Auto-generated from Python Tests`**
- `POST /generate/markdown` → `200`
- `POST /generate/container` → `200`
- `POST /generate/markdown` → `200`
- assert `name == "RNApp"`
- assert `name == "Calculator"`
- assert `url == f"http://127.0.0.1:{preferred}"`

## Intent

Pactown Ecosystem Orchestrator - Build and manage decentralized microservice ecosystems from Markdown READMEs using markpact sandboxes and a centralized service registry.
