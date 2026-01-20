from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager


def test_node_project_uses_npm_instead_of_pip_even_if_deps_lang_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox_root = tmp_path / "sandboxes"
    manager = SandboxManager(sandbox_root)

    monkeypatch.setattr(manager._dep_cache, "get_cached_venv", lambda _deps: None)

    import pactown.sandbox_manager as sm_module

    captured: dict[str, object] = {"npm": 0, "pip": 0}

    def fake_run(cmd, capture_output=False, text=False, check=False, env=None, cwd=None, **kwargs):
        cmd0 = str(cmd[0]) if isinstance(cmd, list) and cmd else str(cmd)
        if isinstance(cmd, list) and cmd0 == "npm":
            captured["npm"] = int(captured["npm"]) + 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if isinstance(cmd, list) and "pip" in cmd0 and "install" in cmd:
            captured["pip"] = int(captured["pip"]) + 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sm_module.subprocess, "run", fake_run)

    readme = """# Express Hello

```javascript markpact:file path=index.js
console.log('hello');
```

```python markpact:deps
express
```

```bash markpact:run
node index.js $PORT
```
"""

    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme)

    service = ServiceConfig(name="svc", readme=str(readme_path), port=8000)

    sandbox = manager.create_sandbox(
        service=service,
        readme_path=readme_path,
        install_dependencies=True,
        on_log=None,
        env=None,
    )

    assert (Path(sandbox.path) / "package.json").exists()
    assert int(captured["npm"]) == 1
    assert int(captured["pip"]) == 0


def test_node_deps_block_creates_package_json_and_calls_npm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox_root = tmp_path / "sandboxes"
    manager = SandboxManager(sandbox_root)

    monkeypatch.setattr(manager._dep_cache, "get_cached_venv", lambda _deps: None)

    import pactown.sandbox_manager as sm_module

    captured: dict[str, object] = {"npm": 0}

    def fake_run(cmd, capture_output=False, text=False, check=False, env=None, cwd=None, **kwargs):
        if isinstance(cmd, list) and cmd and str(cmd[0]) == "npm":
            captured["npm"] = int(captured["npm"]) + 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sm_module.subprocess, "run", fake_run)

    readme = """# Express Hello

```javascript markpact:file path=index.js
console.log('hello');
```

```node markpact:deps
express
```

```bash markpact:run
node index.js $PORT
```
"""

    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme)

    service = ServiceConfig(name="svc", readme=str(readme_path), port=8000)

    sandbox = manager.create_sandbox(
        service=service,
        readme_path=readme_path,
        install_dependencies=True,
        on_log=None,
        env=None,
    )

    pkg = (Path(sandbox.path) / "package.json")
    assert pkg.exists()
    assert "express" in pkg.read_text(encoding="utf-8")
    assert int(captured["npm"]) == 1
