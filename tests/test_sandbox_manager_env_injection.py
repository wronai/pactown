import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pactown.config import ServiceConfig
from pactown.sandbox_manager import SandboxManager


def test_sandbox_manager_passes_env_to_pip_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox_root = tmp_path / "sandboxes"
    manager = SandboxManager(sandbox_root)

    monkeypatch.setattr(manager._dep_cache, "get_cached_venv", lambda _deps: None)

    def fake_ensure_venv(sandbox, verbose=False):
        venv_bin = Path(sandbox.path) / ".venv" / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / "pip").write_text("#!/bin/sh\necho pip\n")
        try:
            (venv_bin / "pip").chmod(0o755)
        except Exception:
            pass

    import pactown.sandbox_manager as sm_module

    monkeypatch.setattr(sm_module, "ensure_venv", fake_ensure_venv)

    captured = {}

    def fake_run(cmd, capture_output=False, text=False, check=False, env=None, **kwargs):
        if isinstance(cmd, list) and "pip" in str(cmd[0]) and "install" in cmd:
            captured["pip_env"] = dict(env or {})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sm_module.subprocess, "run", fake_run)

    readme = """```python markpact:file path=main.py
print('hi')
```
```text markpact:deps
requests
```
"""

    readme_path = tmp_path / "README.md"
    readme_path.write_text(readme)

    service = ServiceConfig(name="svc", readme=str(readme_path), port=8000)

    manager.create_sandbox(
        service=service,
        readme_path=readme_path,
        install_dependencies=True,
        on_log=None,
        env={"PIP_INDEX_URL": "http://pypi-proxy.local/simple"},
    )

    assert "pip_env" in captured
    assert captured["pip_env"]["PIP_INDEX_URL"] == "http://pypi-proxy.local/simple"
