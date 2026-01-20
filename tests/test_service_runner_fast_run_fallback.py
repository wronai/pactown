import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pactown.config import CacheConfig
from pactown.service_runner import ServiceRunner


def test_fast_run_fallback_sets_serviceconfig_readme_and_cleans_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = ServiceRunner(
        sandbox_root=tmp_path / "sandboxes",
        enable_fast_start=False,
        cache_config=CacheConfig(),
    )

    async def allow(*args, **kwargs):
        return SimpleNamespace(allowed=True, reason=None, delay_seconds=0.0)

    monkeypatch.setattr(runner.security_policy, "check_can_start_service", allow)

    from pactown import service_runner as sr_module

    monkeypatch.setattr(sr_module, "kill_process_on_port", lambda _port: False)

    captured = {}

    def fake_create_sandbox(config, readme_path, install_dependencies=True, on_log=None, env=None):
        captured["config_readme"] = config.readme
        captured["readme_path"] = readme_path
        captured["env"] = env
        # Readme file should exist while sandbox is being created
        assert Path(config.readme).exists()
        assert readme_path.exists()
        sandbox_path = tmp_path / "sandbox"
        sandbox_path.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(path=sandbox_path)

    monkeypatch.setattr(runner.sandbox_manager, "create_sandbox", fake_create_sandbox)
    runner.sandbox_manager._processes = {}

    class DummyPopen:
        def __init__(self):
            self.pid = 12345
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")

        def poll(self):
            return None

    import subprocess as subprocess_module

    monkeypatch.setattr(subprocess_module, "Popen", lambda *a, **k: DummyPopen())

    content = """```python markpact:file path=main.py
print('hi')
```
```bash markpact:run
python main.py
```"""

    result = asyncio.run(
        runner.fast_run(
            service_id="svc",
            content=content,
            port=8123,
            env={"PIP_INDEX_URL": "http://pypi-proxy.local/simple"},
            skip_health_check=True,
        )
    )

    assert result.success is True
    assert "readme_path" in captured
    assert captured["config_readme"] == str(captured["readme_path"])
    assert captured["env"] == {"PIP_INDEX_URL": "http://pypi-proxy.local/simple"}

    # The temp file should be removed by the finally block
    assert not captured["readme_path"].exists()
