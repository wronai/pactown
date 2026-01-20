from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager


def test_create_sandbox_writes_iac_manifest_and_compose_and_dockerfile() -> None:
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

        svc = ServiceConfig(name="api", readme=str(readme_path), port=8001, health_check="/health")
        manager = SandboxManager(sandbox_root)
        sandbox = manager.create_sandbox(svc, readme_path, install_dependencies=False, env={"X": "1"})

        assert (sandbox.path / "pactown.sandbox.yaml").exists()
        assert (sandbox.path / "Dockerfile").exists()
        assert (sandbox.path / "docker-compose.yaml").exists()

        spec = yaml.safe_load((sandbox.path / "pactown.sandbox.yaml").read_text())
        assert spec["kind"] == "Sandbox"
        assert spec["metadata"]["name"] == "api"
        assert spec["spec"]["runtime"]["type"] == "python"
        assert spec["spec"]["run"]["port"] == 8001
        assert spec["spec"]["health"]["path"] == "/health"
        assert "X" in spec["spec"]["env"]["keys"]


def test_create_sandbox_node_inferred_writes_manifest() -> None:
    readme = """# Demo Node Service

```js markpact:file path=server.js
const port = process.env.MARKPACT_PORT || process.env.PORT || 3000;
console.log('port', port);
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

        assert (sandbox.path / "pactown.sandbox.yaml").exists()
        spec = yaml.safe_load((sandbox.path / "pactown.sandbox.yaml").read_text())
        assert spec["spec"]["runtime"]["type"] == "node"
        assert (sandbox.path / "package.json").exists()
