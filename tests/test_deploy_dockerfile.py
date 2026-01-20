"""Tests for Dockerfile generation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from pactown.deploy.base import DeploymentConfig
from pactown.deploy.docker import DockerBackend
from pactown.sandbox_manager import SandboxManager
from pactown.config import ServiceConfig


def test_python_dockerfile_healthcheck_does_not_use_curl() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    with TemporaryDirectory() as tmp:
        sandbox_path = Path(tmp)
        (sandbox_path / "requirements.txt").write_text("fastapi\n")

        dockerfile = backend._create_dockerfile(sandbox_path, base_image="python:3.12-slim")

    assert "curl" not in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "python -c" in dockerfile
    assert "MARKPACT_PORT" in dockerfile


def test_python_dockerfile_supports_pip_timeout_and_retries_build_args() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    with TemporaryDirectory() as tmp:
        sandbox_path = Path(tmp)
        (sandbox_path / "requirements.txt").write_text("fastapi\n")

        dockerfile = backend._create_dockerfile(sandbox_path, base_image="python:3.12-slim")

    assert "ARG PIP_DEFAULT_TIMEOUT" in dockerfile
    assert "ARG PIP_RETRIES" in dockerfile
    assert "ENV PIP_DEFAULT_TIMEOUT" in dockerfile
    assert "ENV PIP_RETRIES" in dockerfile


def test_node_dockerfile_falls_back_when_package_lock_missing() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    with TemporaryDirectory() as tmp:
        sandbox_path = Path(tmp)
        (sandbox_path / "package.json").write_text('{"name":"test","version":"1.0.0"}\n')

        dockerfile = backend._create_dockerfile(sandbox_path, base_image="python:3.12-slim")

    assert "curl" not in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm install" in dockerfile
    assert "package-lock.json" in dockerfile
    assert "node -e" in dockerfile
    assert "MARKPACT_PORT" in dockerfile


def test_markpact_readme_python_materializes_and_generates_cmd_from_run_block() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    readme = """# Demo API

```python markpact:deps
fastapi
uvicorn
```

```python markpact:file path=main.py
from fastapi import FastAPI

app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8000}
```
"""

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_root = root / "sandboxes"
        readme_path = root / "README.md"
        readme_path.write_text(readme)

        svc = ServiceConfig(name="api", readme=str(readme_path), port=8001)
        manager = SandboxManager(sandbox_root)
        sandbox = manager.create_sandbox(svc, readme_path, install_dependencies=False)

        assert (sandbox.path / "main.py").exists()
        assert (sandbox.path / "requirements.txt").exists()

        run_cmd = "uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8000}"
        dockerfile = backend._create_dockerfile(sandbox.path, base_image="python:3.12-slim", run_cmd=run_cmd)

        assert "CMD" in dockerfile
        assert "sh" in dockerfile
        assert "uvicorn main:app" in dockerfile


def test_markpact_readme_node_materializes_package_json_and_generates_cmd_from_run_block() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    readme = """# Demo Node Service

```js markpact:deps
express
```

```js markpact:file path=server.js
const express = require('express');
const app = express();
const port = process.env.MARKPACT_PORT || process.env.PORT || 3000;

app.get('/health', (_req, res) => res.json({ ok: true }));
app.listen(port, '0.0.0.0', () => console.log('listening', port));
```

```bash markpact:run
node server.js
```
"""

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_root = root / "sandboxes"
        readme_path = root / "README.md"
        readme_path.write_text(readme)

        svc = ServiceConfig(name="node", readme=str(readme_path), port=8002)
        manager = SandboxManager(sandbox_root)
        sandbox = manager.create_sandbox(svc, readme_path, install_dependencies=False)

        assert (sandbox.path / "server.js").exists()
        # Node detection should ensure package.json exists for docker build context
        assert (sandbox.path / "package.json").exists()

        run_cmd = "node server.js"
        dockerfile = backend._create_dockerfile(sandbox.path, base_image="python:3.12-slim", run_cmd=run_cmd)

        assert "FROM node:20-slim" in dockerfile
        assert "npm install" in dockerfile
        assert "CMD" in dockerfile
        assert "node server.js" in dockerfile


def test_markpact_readme_static_web_no_deps_generates_cmd_from_run_block() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    readme = """# Static Web

```html markpact:file path=public/index.html
<!doctype html>
<html>
  <head><meta charset=\"utf-8\" /><title>OK</title></head>
  <body>hello</body>
</html>
```

```bash markpact:run
python -m http.server ${MARKPACT_PORT:-8000} --directory public
```
"""

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_root = root / "sandboxes"
        readme_path = root / "README.md"
        readme_path.write_text(readme)

        svc = ServiceConfig(name="web", readme=str(readme_path), port=8003)
        manager = SandboxManager(sandbox_root)
        sandbox = manager.create_sandbox(svc, readme_path, install_dependencies=False)

        assert (sandbox.path / "public" / "index.html").exists()
        assert not (sandbox.path / "requirements.txt").exists()

        run_cmd = "python -m http.server ${MARKPACT_PORT:-8000} --directory public"
        dockerfile = backend._create_dockerfile(sandbox.path, base_image="python:3.12-slim", run_cmd=run_cmd)

        assert "CMD" in dockerfile
        assert "http.server" in dockerfile
