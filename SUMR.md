# Pactown 🏘️

SUMD - Structured Unified Markdown Descriptor for AI-aware project refactorization

## Contents

- [Metadata](#metadata)
- [Architecture](#architecture)
- [Workflows](#workflows)
- [Quality Pipeline (`pyqual.yaml`)](#quality-pipeline-pyqualyaml)
- [Dependencies](#dependencies)
- [Call Graph](#call-graph)
- [Test Contracts](#test-contracts)
- [Refactoring Analysis](#refactoring-analysis)
- [Intent](#intent)

## Metadata

- **name**: `pactown`
- **version**: `0.1.170`
- **python_requires**: `>=3.10`
- **license**: {'text': 'Apache-2.0'}
- **ai_model**: `openrouter/qwen/qwen3-coder-next`
- **ecosystem**: SUMD + DOQL + testql + taskfile
- **generated_from**: pyproject.toml, requirements-dev.txt, Makefile, testql(3), app.doql.less, pyqual.yaml, goal.yaml, .env.example, project/(5 analysis files)

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

## Refactoring Analysis

*Pre-refactoring snapshot — use this section to identify targets. Generated from `project/` toon files.*

### Call Graph & Complexity (`project/calls.toon.yaml`)

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

### Code Analysis (`project/analysis.toon.yaml`)

```toon markpact:analysis path=project/analysis.toon.yaml
# code2llm | 62f 21094L | python:50,yaml:5,shell:2,txt:1,cfg:1,toml:1,ini:1 | 2026-06-06
# generated in 0.03s
# CC̅=4.5 | critical:33/603 | dups:0 | cycles:0

HEALTH[20]:
  🔴 GOD   src/pactown/fast_start.py = 754L, 7 classes, 26m, max CC=20
  🔴 GOD   src/pactown/deploy/quadlet.py = 1044L, 4 classes, 28m, max CC=18
  🔴 GOD   src/pactown/security.py = 690L, 9 classes, 32m, max CC=14
  🔴 GOD   src/pactown/events.py = 1075L, 13 classes, 75m, max CC=19
  🔴 GOD   src/pactown/runner_api.py = 635L, 8 classes, 19m, max CC=14
  🔴 GOD   src/pactown/deploy/quadlet_api.py = 539L, 7 classes, 2m, max CC=1
  🟡 CC    _sanitize_inherited_env CC=16 (limit:15)
  🟡 CC    extract_run_command CC=17 (limit:15)
  🟡 CC    build_error_context CC=41 (limit:15)
  🟡 CC    render_error_report_md CC=43 (limit:15)
  🟡 CC    build_sandbox_spec CC=17 (limit:15)
  🟡 CC    get_or_create_user CC=15 (limit:15)
  🟡 CC    validate_content CC=25 (limit:15)
  🟡 CC    _extract_required_env_vars CC=19 (limit:15)
  🟡 CC    run_from_content CC=37 (limit:15)
  🟡 CC    _generate_suggestions CC=18 (limit:15)
  🟡 CC    _wait_for_health CC=30 (limit:15)
  🟡 CC    fast_run CC=36 (limit:15)
  🟡 CC    _scaffold_capacitor CC=24 (limit:15)
  🟡 CC    kill_process_on_port CC=25 (limit:15)

REFACTOR[7]:
  1. split src/pactown/fast_start.py  (god module)
  2. split src/pactown/deploy/quadlet.py  (god module)
  3. split src/pactown/security.py  (god module)
  4. split src/pactown/events.py  (god module)
  5. split src/pactown/runner_api.py  (god module)
  6. split src/pactown/deploy/quadlet_api.py  (god module)
  7. split 14 high-CC methods  (CC>15)

PIPELINES[451]:
  [1] Src [main]: main
      PURITY: 100% pure
  [2] Src [_heartbeat]: _heartbeat → _should_emit_to_ui → _ui_log_level
      PURITY: 100% pure
  [3] Src [main]: main
      PURITY: 100% pure
  [4] Src [get_logger]: get_logger
      PURITY: 100% pure
  [5] Src [setup_logging]: setup_logging
      PURITY: 100% pure
  [6] Src [main]: main
      PURITY: 100% pure
  [7] Src [from_env]: from_env
      PURITY: 100% pure
  [8] Src [to_dict]: to_dict
      PURITY: 100% pure
  [9] Src [__init__]: __init__
      PURITY: 100% pure
  [10] Src [can_isolate]: can_isolate
      PURITY: 100% pure
  [11] Src [_load_existing_users]: _load_existing_users
      PURITY: 100% pure
  [12] Src [_generate_username]: _generate_username
      PURITY: 100% pure
  [13] Src [get_or_create_user]: get_or_create_user → _sanitize_gecos
      PURITY: 100% pure
  [14] Src [get_user]: get_user
      PURITY: 100% pure
  [15] Src [get_sandbox_path]: get_sandbox_path
      PURITY: 100% pure
  [16] Src [run_as_user]: run_as_user
      PURITY: 100% pure
  [17] Src [list_users]: list_users → list
      PURITY: 100% pure
  [18] Src [get_user_stats]: get_user_stats → list
      PURITY: 100% pure
  [19] Src [export_user_data]: export_user_data
      PURITY: 100% pure
  [20] Src [import_user_data]: import_user_data
      PURITY: 100% pure
  [21] Src [delete_user]: delete_user
      PURITY: 100% pure
  [22] Src [__init__]: __init__ → get_security_policy
      PURITY: 100% pure
  [23] Src [validate_content]: validate_content → extract_run_command → extract_target_config
      PURITY: 100% pure
  [24] Src [_extract_required_env_vars]: _extract_required_env_vars
      PURITY: 100% pure
  [25] Src [_missing_required_env_vars]: _missing_required_env_vars
      PURITY: 100% pure
  [26] Src [_prune_stale_user_services]: _prune_stale_user_services → list
      PURITY: 100% pure
  [27] Src [run_from_content]: run_from_content → kill_process_on_port
      PURITY: 100% pure
  [28] Src [_generate_suggestions]: _generate_suggestions
      PURITY: 100% pure
  [29] Src [_wait_for_health]: _wait_for_health
      PURITY: 100% pure
  [30] Src [stop]: stop
      PURITY: 100% pure
  [31] Src [get_status]: get_status
      PURITY: 100% pure
  [32] Src [list_services]: list_services
      PURITY: 100% pure
  [33] Src [test_endpoints]: test_endpoints
      PURITY: 100% pure
  [34] Src [stop_all]: stop_all → list
      PURITY: 100% pure
  [35] Src [fast_run]: fast_run → kill_process_on_port
      PURITY: 100% pure
  [36] Src [_quick_health_check]: _quick_health_check
      PURITY: 100% pure
  [37] Src [get_cache_stats]: get_cache_stats
      PURITY: 100% pure
  [38] Src [from_dict]: from_dict
      PURITY: 100% pure
  [39] Src [from_dict]: from_dict
      PURITY: 100% pure
  [40] Src [from_env]: from_env
      PURITY: 100% pure
  [41] Src [_to_mapping]: _to_mapping
      PURITY: 100% pure
  [42] Src [to_env]: to_env
      PURITY: 100% pure
  [43] Src [to_docker_build_args]: to_docker_build_args
      PURITY: 100% pure
  [44] Src [from_yaml]: from_yaml
      PURITY: 100% pure
  [45] Src [from_dict]: from_dict
      PURITY: 100% pure
  [46] Src [to_dict]: to_dict
      PURITY: 100% pure
  [47] Src [to_yaml]: to_yaml
      PURITY: 100% pure
  [48] Src [from_yaml_body]: from_yaml_body
      PURITY: 100% pure
  [49] Src [from_dict]: from_dict → _to_int
      PURITY: 100% pure
  [50] Src [infer_target_from_deps]: infer_target_from_deps
      PURITY: 100% pure

LAYERS:
  tools/                          CC̄=5.4    ←in:0  →out:0
  │ !! validate_artifacts_docker   546L  2C   11m  CC=17     ←0
  │ sync_pactown_com_dependency    89L  0C    3m  CC=8      ←0
  │
  examples/                       CC̄=5.3    ←in:0  →out:0
  │ demo                       120L  0C    1m  CC=4      ←0
  │ demo                       110L  0C    1m  CC=5      ←0
  │ demo                       105L  0C    1m  CC=7      ←0
  │ saas.pactown.yaml           72L  0C    0m  CC=0.0    ←0
  │ saas.pactown.yaml           48L  0C    0m  CC=0.0    ←0
  │
  src/                            CC̄=4.5    ←in:0  →out:0
  │ !! sandbox_manager           1839L  2C   24m  CC=67     ←0
  │ !! service_runner            1234L  1C   16m  CC=37     ←0
  │ !! events                    1075L  13C   75m  CC=19     ←0
  │ !! quadlet                   1044L  4C   28m  CC=18     ←3
  │ !! cli                        990L  0C   34m  CC=18     ←0
  │ !! fast_start                 754L  7C   26m  CC=20     ←0
  │ !! security                   690L  9C   32m  CC=14     ←3
  │ !! desktop                    665L  1C   15m  CC=19     ←0
  │ !! runner_api                 635L  8C   19m  CC=14     ←0
  │ !! ansible                    586L  2C   18m  CC=10     ←0
  │ !! quadlet_shell              564L  1C   23m  CC=9      ←1
  │ !! quadlet_api                539L  7C    2m  CC=1      ←1
  │ kubernetes                 473L  1C   12m  CC=9      ←0
  │ !! mobile                     471L  1C   10m  CC=24     ←0
  │ !! user_isolation             463L  2C   16m  CC=15     ←1
  │ !! orchestrator               455L  2C   18m  CC=19     ←0
  │ llm                        453L  3C   22m  CC=8      ←0
  │ !! compose                    439L  2C    7m  CC=18     ←1
  │ !! podman                     421L  1C    9m  CC=17     ←0
  │ !! error_context              381L  1C    9m  CC=43     ←2
  │ targets                    351L  6C    7m  CC=10     ←3
  │ !! docker                     321L  1C    7m  CC=16     ←0
  │ base                       312L  5C   13m  CC=5      ←0
  │ parallel                   271L  2C    6m  CC=12     ←0
  │ network                    270L  3C   17m  CC=6      ←0
  │ client                     260L  2C   21m  CC=6      ←0
  │ !! iac                        258L  1C    8m  CC=17     ←1
  │ node_cache                 258L  2C   12m  CC=7      ←0
  │ !! runner_types               254L  6C    3m  CC=25     ←1
  │ config                     252L  5C   11m  CC=12     ←3
  │ __init__                   240L  0C    0m  CC=0.0    ←0
  │ !! sandbox_helpers            234L  0C   10m  CC=16     ←3
  │ server                     217L  4C    2m  CC=1      ←0
  │ generator                  213L  0C    4m  CC=12     ←1
  │ nfo_config                 210L  0C    2m  CC=11     ←0
  │ resolver                   162L  2C    8m  CC=9      ←0
  │ models                     157L  3C   14m  CC=6      ←14
  │ base                       155L  3C    4m  CC=13     ←3
  │ platform                   146L  2C   15m  CC=5      ←1
  │ web                         93L  1C    2m  CC=4      ←0
  │ !! markpact_blocks             69L  0C    3m  CC=17     ←3
  │ __init__                    34L  0C    0m  CC=0.0    ←0
  │ registry                    32L  0C    2m  CC=2      ←1
  │ __init__                    18L  0C    0m  CC=0.0    ←0
  │ __init__                    12L  0C    0m  CC=0.0    ←0
  │
  ./                              CC̄=0.0    ←in:0  →out:0
  │ goal.yaml                  431L  0C    0m  CC=0.0    ←0
  │ Makefile                   328L  0C    0m  CC=0.0    ←0
  │ pyproject.toml             112L  0C    0m  CC=0.0    ←0
  │ project.sh                  59L  0C    0m  CC=0.0    ←0
  │ pyqual.yaml                 55L  0C    0m  CC=0.0    ←0
  │ saas.pactown.yaml           22L  0C    0m  CC=0.0    ←0
  │ .bumpversion.cfg            20L  0C    0m  CC=0.0    ←0
  │ requirements-dev.txt         3L  0C    0m  CC=0.0    ←0
  │ pytest.ini                   3L  0C    0m  CC=0.0    ←0
  │ tree.sh                      1L  0C    0m  CC=0.0    ←0
  │

COUPLING: no cross-package imports detected

EXTERNAL:
  validation: run `vallm batch .` → validation.toon
  duplication: run `redup scan .` → duplication.toon
```

### Duplication (`project/duplication.toon.yaml`)

```toon markpact:analysis path=project/duplication.toon.yaml
# redup/duplication | 15 groups | 50f 19940L | 2026-06-06

SUMMARY:
  files_scanned: 50
  total_lines:   19940
  dup_groups:    15
  dup_fragments: 38
  saved_lines:   152
  scan_ms:       4728

HOTSPOTS[7] (files with most duplication):
  src/pactown/deploy/docker.py  dup=81L  groups=4  frags=4  (0.4%)
  src/pactown/deploy/podman.py  dup=80L  groups=4  frags=4  (0.4%)
  src/pactown/events.py  dup=22L  groups=2  frags=7  (0.1%)
  src/pactown/sandbox_manager.py  dup=19L  groups=2  frags=4  (0.1%)
  src/pactown/cli.py  dup=17L  groups=2  frags=5  (0.1%)
  src/pactown/fast_start.py  dup=12L  groups=2  frags=2  (0.1%)
  tools/validate_artifacts_docker.py  dup=9L  groups=1  frags=2  (0.0%)

DUPLICATES[15] (ranked by impact):
  [3bc7293818917112] ! STRU  push_image  L=37 N=2 saved=37 sim=1.00
      src/pactown/deploy/docker.py:115-151  (push_image)
      src/pactown/deploy/podman.py:131-166  (push_image)
  [31c4a0512c36df3e]   STRU  stop  L=21 N=2 saved=21 sim=1.00
      src/pactown/deploy/docker.py:264-284  (stop)
      src/pactown/deploy/podman.py:288-308  (stop)
  [afe5dfa59ad76ed4]   STRU  get_service_commands  L=3 N=6 saved=15 sim=1.00
      src/pactown/events.py:1048-1050  (get_service_commands)
      src/pactown/events.py:1053-1055  (get_service_queries)
      src/pactown/events.py:1058-1060  (get_project_commands)
      src/pactown/events.py:1063-1065  (get_project_queries)
      src/pactown/events.py:1068-1070  (get_security_commands)
      src/pactown/events.py:1073-1075  (get_security_queries)
  [f66494c89380b630]   STRU  is_available  L=12 N=2 saved=12 sim=1.00
      src/pactown/deploy/docker.py:33-44  (is_available)
      src/pactown/deploy/podman.py:45-56  (is_available)
  [d35fa402e5867c64]   STRU  logs  L=11 N=2 saved=11 sim=1.00
      src/pactown/deploy/docker.py:286-296  (logs)
      src/pactown/deploy/podman.py:310-320  (logs)
  [518ba2ff9377d51e]   EXAC  _log  L=3 N=4 saved=9 sim=1.00
      src/pactown/builders/desktop.py:75-77  (_log)
      src/pactown/builders/desktop.py:510-512  (_log)
      src/pactown/builders/mobile.py:107-109  (_log)
      src/pactown/builders/web.py:61-63  (_log)
  [649f86edf66a0a7d]   STRU  dbg  L=4 N=3 saved=8 sim=1.00
      src/pactown/sandbox_manager.py:615-618  (dbg)
      src/pactown/sandbox_manager.py:763-766  (dbg)
      src/pactown/sandbox_manager.py:1121-1124  (dbg)
  [be52ebb0de897de3]   EXAC  _copytree_fast  L=7 N=2 saved=7 sim=1.00
      src/pactown/fast_start.py:214-220  (_copytree_fast)
      src/pactown/sandbox_manager.py:942-948  (_copytree_fast)
  [aaae754bdb04529d]   STRU  cli  L=3 N=3 saved=6 sim=1.00
      src/pactown/cli.py:60-62  (cli)
      src/pactown/cli.py:523-525  (quadlet)
      src/pactown/cli.py:754-756  (llm)
  [c13e6a51a1c9d3d8]   EXAC  _beat_every_s  L=5 N=2 saved=5 sim=1.00
      src/pactown/fast_start.py:83-87  (_beat_every_s)
      src/pactown/sandbox_helpers.py:206-210  (_beat_every_s)
  [42bbb53e953efc4f]   STRU  _py_script  L=5 N=2 saved=5 sim=1.00
      tools/validate_artifacts_docker.py:154-158  (_py_script)
      tools/validate_artifacts_docker.py:161-164  (_py_yaml_script)
  [e9e1cf2a479396c3]   EXAC  log  L=4 N=2 saved=4 sim=1.00
      src/pactown/service_runner.py:301-304  (log)
      src/pactown/service_runner.py:945-948  (log)
  [b0f54d48b543ed9a]   STRU  is_lolm_available  L=4 N=2 saved=4 sim=1.00
      src/pactown/cli.py:28-31  (is_lolm_available)
      src/pactown/cli.py:34-37  (get_llm_status)
  [c55429a05bfee580]   STRU  set_event_store  L=4 N=2 saved=4 sim=1.00
      src/pactown/events.py:366-369  (set_event_store)
      src/pactown/security.py:687-690  (set_security_policy)
  [5c99f8b82f410645]   STRU  write_sandbox_manifest  L=4 N=2 saved=4 sim=1.00
      src/pactown/iac.py:125-128  (write_sandbox_manifest)
      src/pactown/iac.py:200-203  (write_single_service_compose)

REFACTOR[15] (ranked by priority):
  [1] ◐ extract_function   → src/pactown/deploy/utils/push_image.py
      WHY: 2 occurrences of 37-line block across 2 files — saves 37 lines
      FILES: src/pactown/deploy/docker.py, src/pactown/deploy/podman.py
  [2] ○ extract_function   → src/pactown/deploy/utils/stop.py
      WHY: 2 occurrences of 21-line block across 2 files — saves 21 lines
      FILES: src/pactown/deploy/docker.py, src/pactown/deploy/podman.py
  [3] ○ extract_function   → src/pactown/utils/get_service_commands.py
      WHY: 6 occurrences of 3-line block across 1 files — saves 15 lines
      FILES: src/pactown/events.py
  [4] ○ extract_function   → src/pactown/deploy/utils/is_available.py
      WHY: 2 occurrences of 12-line block across 2 files — saves 12 lines
      FILES: src/pactown/deploy/docker.py, src/pactown/deploy/podman.py
  [5] ○ extract_function   → src/pactown/deploy/utils/logs.py
      WHY: 2 occurrences of 11-line block across 2 files — saves 11 lines
      FILES: src/pactown/deploy/docker.py, src/pactown/deploy/podman.py
  [6] ○ extract_function   → src/pactown/builders/utils/_log.py
      WHY: 4 occurrences of 3-line block across 3 files — saves 9 lines
      FILES: src/pactown/builders/desktop.py, src/pactown/builders/mobile.py, src/pactown/builders/web.py
  [7] ○ extract_function   → src/pactown/utils/dbg.py
      WHY: 3 occurrences of 4-line block across 1 files — saves 8 lines
      FILES: src/pactown/sandbox_manager.py
  [8] ○ extract_function   → src/pactown/utils/_copytree_fast.py
      WHY: 2 occurrences of 7-line block across 2 files — saves 7 lines
      FILES: src/pactown/fast_start.py, src/pactown/sandbox_manager.py
  [9] ○ extract_function   → src/pactown/utils/cli.py
      WHY: 3 occurrences of 3-line block across 1 files — saves 6 lines
      FILES: src/pactown/cli.py
  [10] ○ extract_function   → src/pactown/utils/_beat_every_s.py
      WHY: 2 occurrences of 5-line block across 2 files — saves 5 lines
      FILES: src/pactown/fast_start.py, src/pactown/sandbox_helpers.py
  [11] ○ extract_function   → tools/utils/_py_script.py
      WHY: 2 occurrences of 5-line block across 1 files — saves 5 lines
      FILES: tools/validate_artifacts_docker.py
  [12] ○ extract_function   → src/pactown/utils/log.py
      WHY: 2 occurrences of 4-line block across 1 files — saves 4 lines
      FILES: src/pactown/service_runner.py
  [13] ○ extract_function   → src/pactown/utils/is_lolm_available.py
      WHY: 2 occurrences of 4-line block across 1 files — saves 4 lines
      FILES: src/pactown/cli.py
  [14] ○ extract_function   → src/pactown/utils/set_event_store.py
      WHY: 2 occurrences of 4-line block across 2 files — saves 4 lines
      FILES: src/pactown/events.py, src/pactown/security.py
  [15] ○ extract_function   → src/pactown/utils/write_sandbox_manifest.py
      WHY: 2 occurrences of 4-line block across 1 files — saves 4 lines
      FILES: src/pactown/iac.py

QUICK_WINS[8] (low risk, high savings — do first):
  [2] extract_function   saved=21L  → src/pactown/deploy/utils/stop.py
      FILES: docker.py, podman.py
  [3] extract_function   saved=15L  → src/pactown/utils/get_service_commands.py
      FILES: events.py
  [4] extract_function   saved=12L  → src/pactown/deploy/utils/is_available.py
      FILES: docker.py, podman.py
  [5] extract_function   saved=11L  → src/pactown/deploy/utils/logs.py
      FILES: docker.py, podman.py
  [6] extract_function   saved=9L  → src/pactown/builders/utils/_log.py
      FILES: desktop.py, mobile.py, web.py
  [7] extract_function   saved=8L  → src/pactown/utils/dbg.py
      FILES: sandbox_manager.py
  [8] extract_function   saved=7L  → src/pactown/utils/_copytree_fast.py
      FILES: fast_start.py, sandbox_manager.py
  [9] extract_function   saved=6L  → src/pactown/utils/cli.py
      FILES: cli.py

EFFORT_ESTIMATE (total ≈ 5.7h):
  hard   push_image                          saved=37L  ~111min
  medium stop                                saved=21L  ~42min
  medium get_service_commands                saved=15L  ~30min
  easy   is_available                        saved=12L  ~24min
  easy   logs                                saved=11L  ~22min
  easy   _log                                saved=9L  ~18min
  easy   dbg                                 saved=8L  ~16min
  easy   _copytree_fast                      saved=7L  ~14min
  easy   cli                                 saved=6L  ~12min
  easy   _beat_every_s                       saved=5L  ~10min
  ... +5 more (~42min)

METRICS-TARGET:
  dup_groups:  15 → 0
  saved_lines: 152 lines recoverable
```

### Evolution / Churn (`project/evolution.toon.yaml`)

```toon markpact:analysis path=project/evolution.toon.yaml
# code2llm/evolution | 600 func | 43f | 2026-06-06
# generated in 0.00s

NEXT[10] (ranked by impact):
  [1] !! SPLIT           src/pactown/sandbox_manager.py
      WHY: 1839L, 2 classes, max CC=67
      EFFORT: ~4h  IMPACT: 123213

  [2] !! SPLIT           src/pactown/service_runner.py
      WHY: 1234L, 1 classes, max CC=37
      EFFORT: ~4h  IMPACT: 45658

  [3] !! SPLIT           src/pactown/events.py
      WHY: 1075L, 13 classes, max CC=19
      EFFORT: ~4h  IMPACT: 20425

  [4] !! SPLIT-FUNC      SandboxManager.create_sandbox  CC=67  fan=78
      WHY: CC=67 exceeds 15
      EFFORT: ~1h  IMPACT: 5226

  [5] !! SPLIT-FUNC      SandboxManager.start_service  CC=53  fan=66
      WHY: CC=53 exceeds 15
      EFFORT: ~1h  IMPACT: 3498

  [6] !! SPLIT-FUNC      SandboxManager.build_service  CC=40  fan=45
      WHY: CC=40 exceeds 15
      EFFORT: ~1h  IMPACT: 1800

  [7] !! SPLIT-FUNC      ServiceRunner.fast_run  CC=36  fan=48
      WHY: CC=36 exceeds 15
      EFFORT: ~1h  IMPACT: 1728

  [8] !! SPLIT-FUNC      ServiceRunner.run_from_content  CC=37  fan=41
      WHY: CC=37 exceeds 15
      EFFORT: ~1h  IMPACT: 1517

  [9] !! SPLIT-FUNC      SandboxManager._install_node_deps  CC=34  fan=36
      WHY: CC=34 exceeds 15
      EFFORT: ~1h  IMPACT: 1224

  [10] !! SPLIT-FUNC      build_error_context  CC=41  fan=29
      WHY: CC=41 exceeds 15
      EFFORT: ~1h  IMPACT: 1189


RISKS[3]:
  ⚠ Splitting src/pactown/sandbox_manager.py may break 24 import paths
  ⚠ Splitting src/pactown/service_runner.py may break 16 import paths
  ⚠ Splitting src/pactown/events.py may break 75 import paths

METRICS-TARGET:
  CC̄:          4.5 → ≤3.1
  max-CC:      67 → ≤20
  god-modules: 13 → 0
  high-CC(≥15): 33 → ≤16
  hub-types:   0 → ≤0

PATTERNS (language parser shared logic):
  _extract_declarations() in base.py — unified extraction for:
    - TypeScript: interfaces, types, classes, functions, arrow funcs
    - PHP: namespaces, traits, classes, functions, includes
    - Ruby: modules, classes, methods, requires
    - C++: classes, structs, functions, #includes
    - C#: classes, interfaces, methods, usings
    - Java: classes, interfaces, methods, imports
    - Go: packages, functions, structs
    - Rust: modules, functions, traits, use statements

  Shared regex patterns per language:
    - import: language-specific import/require/using patterns
    - class: class/struct/trait declarations with inheritance
    - function: function/method signatures with visibility
    - brace_tracking: for C-family languages ({ })
    - end_keyword_tracking: for Ruby (module/class/def...end)

  Benefits:
    - Consistent extraction logic across all languages
    - Reduced code duplication (~70% reduction in parser LOC)
    - Easier maintenance: fix once, apply everywhere
    - Standardized FunctionInfo/ClassInfo models

HISTORY:
  (first run — no previous data)
```

## Intent

Pactown Ecosystem Orchestrator - Build and manage decentralized microservice ecosystems from Markdown READMEs using markpact sandboxes and a centralized service registry.
