import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pactown.runner_api import RunnerApiSettings, RunnerService, create_runner_api
from pactown.service_runner import ErrorCategory, RunResult
from pactown.sandbox_manager import SandboxManager, ServiceProcess


def _sample_markdown() -> str:
    return """# Test Service

```python markpact:file path=main.py
print('hello')
```

```bash markpact:run
python main.py
```
"""


@pytest.mark.asyncio
async def test_validate_ok(tmp_path):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/validate", json={"readme_content": _sample_markdown()})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["valid"] is True
        assert payload["file_count"] == 1
        assert payload["has_run"] is True


@pytest.mark.asyncio
async def test_run_fails_fast_on_missing_required_env_vars(tmp_path):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    readme = """# Ride Sharing App

## Zmienne środowiskowe
- `DATABASE_URL`: URL bazy danych

```text markpact:file path=.env.example
DATABASE_URL=
```

```python markpact:deps
fastapi
uvicorn[standard]
sqlalchemy
psycopg2-binary
geoalchemy2
```

```python markpact:file path=main.py
from fastapi import FastAPI
import os

DATABASE_URL = os.getenv('DATABASE_URL')

app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}
```

```bash markpact:run
uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8000}
```
"""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/run",
            json={
                "project_id": 1,
                "readme_content": readme,
                "port": 0,
                "env": {},
                "user_id": "user:1",
                "username": "user",
                "fast_mode": False,
                "skip_health_check": True,
            },
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is False
        assert payload.get("error_category") in {"environment", "ENVIRONMENT"}
        assert "DATABASE_URL" in (payload.get("message") or "")


@pytest.mark.asyncio
async def test_run_passes_pip_timeout_and_retries_to_pip_install(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PACTOWN_PIP_DEFAULT_TIMEOUT", "60")
    monkeypatch.setenv("PACTOWN_PIP_RETRIES", "5")

    import pactown.service_runner as sr_module

    monkeypatch.setattr(sr_module, "kill_process_on_port", lambda _port, force=False: False)

    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    # Avoid using cached venvs to ensure pip install path is exercised.
    monkeypatch.setattr(runner_service.runner.sandbox_manager._dep_cache, "get_cached_venv", lambda _deps: None)
    monkeypatch.setattr(runner_service.runner.sandbox_manager._dep_cache, "save_existing_venv", lambda *_args, **_kwargs: None)

    import pactown.sandbox_manager as sm_module

    def fake_ensure_venv(sandbox, verbose=False):
        venv_bin = Path(sandbox.path) / ".venv" / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / "pip").write_text("#!/bin/sh\necho pip\n")
        try:
            (venv_bin / "pip").chmod(0o755)
        except Exception:
            pass

    monkeypatch.setattr(sm_module, "ensure_venv", fake_ensure_venv)

    captured: dict[str, object] = {}

    def fake_popen(cmd, stdout=None, stderr=None, text=False, bufsize=0, env=None, **kwargs):
        if isinstance(cmd, list) and cmd and "pip" in str(cmd[0]) and "install" in cmd:
            captured["pip_cmd"] = list(cmd)
            captured["pip_env"] = dict(env or {})
        return SimpleNamespace(stdout=[], wait=lambda: 0, args=cmd)

    monkeypatch.setattr(sm_module.subprocess, "Popen", fake_popen)

    # Don't start a real process; we only care about pip invocation.
    def fake_start_service(
        self,
        service,
        readme_path,
        env,
        verbose: bool = True,
        restart_if_running: bool = False,
        on_log=None,
        user_id=None,
    ) -> ServiceProcess:
        sandbox = self.create_sandbox(
            service=service,
            readme_path=readme_path,
            install_dependencies=True,
            on_log=on_log,
            env=env,
        )
        dummy_proc = SimpleNamespace(pid=9999, poll=lambda: None, returncode=None, stderr=None, stdout=None)
        return ServiceProcess(
            name=service.name,
            pid=9999,
            port=service.port,
            sandbox_path=sandbox.path,
            process=dummy_proc,
            started_at=time.time(),
        )

    monkeypatch.setattr(SandboxManager, "start_service", fake_start_service)

    readme = """# Pip Flags Demo

```python markpact:file path=main.py
print('hi')
```

```python markpact:deps
requests
```

```bash markpact:run
python main.py
```
"""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/run",
            json={
                "project_id": 1,
                "readme_content": readme,
                "port": 0,
                "env": {},
                "user_id": "user:1",
                "username": "user",
                "fast_mode": False,
                "skip_health_check": True,
            },
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True

    assert "pip_cmd" in captured
    pip_cmd = captured["pip_cmd"]
    assert "--timeout" in pip_cmd
    assert "--retries" in pip_cmd

    assert "pip_env" in captured
    pip_env = captured["pip_env"]
    assert pip_env.get("PIP_DEFAULT_TIMEOUT") == "60"
    assert pip_env.get("PIP_RETRIES") == "5"


@pytest.mark.asyncio
async def test_sandbox_prepare_and_file_ops(tmp_path):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        service_id = "1-user"

        prep = await client.post(
            "/sandbox/prepare",
            json={
                "project_id": 1,
                "service_id": service_id,
                "readme_content": _sample_markdown(),
                "port": 0,
            },
        )
        assert prep.status_code == 200
        prep_payload = prep.json()
        file_paths = [f["path"] for f in prep_payload.get("files", [])]
        assert "main.py" in file_paths

        read = await client.get(f"/sandbox/{service_id}/file", params={"path": "main.py"})
        assert read.status_code == 200
        assert "print('hello')" in read.json()["content"]

        write = await client.put(
            f"/sandbox/{service_id}/file",
            params={"path": "extra.txt"},
            json={"content": "ok"},
        )
        assert write.status_code == 200

        files = await client.get(f"/sandbox/{service_id}/files")
        assert files.status_code == 200
        file_paths = [f["path"] for f in files.json().get("files", [])]
        assert "extra.txt" in file_paths

        bad = await client.put(
            f"/sandbox/{service_id}/file",
            params={"path": "../escape.txt"},
            json={"content": "no"},
        )
        assert bad.status_code == 400

        delete = await client.delete(f"/sandbox/{service_id}/file", params={"path": "extra.txt"})
        assert delete.status_code == 200

        files2 = await client.get(f"/sandbox/{service_id}/files")
        assert files2.status_code == 200
        file_paths2 = [f["path"] for f in files2.json().get("files", [])]
        assert "extra.txt" not in file_paths2


@pytest.mark.asyncio
async def test_status_filtering(tmp_path):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status", params={"user_id": "user:1"})
        assert resp.status_code == 200
        assert resp.json().get("services") == []


@pytest.mark.asyncio
async def test_run_failure_includes_error_report_md(tmp_path, monkeypatch):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    service_id = "1-user"
    sandbox_path = runner_service._sandbox_path_for(service_id)
    sandbox_path.mkdir(parents=True, exist_ok=True)
    (sandbox_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    file_path = sandbox_path / "main.py"
    stderr = (
        "Traceback (most recent call last):\n"
        f"  File \"{file_path}\", line 1, in <module>\n"
        "    raise RuntimeError('boom')\n"
        "RuntimeError: boom\n"
        "trace_id=abc123\n"
    )

    async def fake_run(
        *,
        service_id: str,
        content: str,
        port: int,
        env,
        user_id,
        username,
        user_profile,
        fast_mode: bool,
        skip_health_check: bool,
        on_log=None,
    ) -> RunResult:
        return RunResult(
            success=False,
            port=int(port or 0),
            pid=None,
            message="boom",
            logs=[],
            error_category=ErrorCategory.PROCESS_CRASH,
            stderr_output=stderr,
        )

    monkeypatch.setattr(runner_service, "run", fake_run)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/run",
            json={
                "project_id": 1,
                "service_id": service_id,
                "readme_content": _sample_markdown(),
                "port": 12000,
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload.get("error_context") is not None
        assert payload.get("error_report_md")

        md = payload["error_report_md"]
        assert "## Summary" in md
        assert "abc123" in md
        assert "### `main.py`" in md
        assert "print('hello')" in md


@pytest.mark.asyncio
async def test_run_stream_failure_includes_error_report_md(tmp_path, monkeypatch):
    settings = RunnerApiSettings()
    settings.require_token = False

    runner_service = RunnerService(sandbox_root=tmp_path, port_start=12000, port_end=12010)
    app = create_runner_api(runner_service=runner_service, settings=settings)

    service_id = "1-user"
    sandbox_path = runner_service._sandbox_path_for(service_id)
    sandbox_path.mkdir(parents=True, exist_ok=True)
    (sandbox_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    file_path = sandbox_path / "main.py"
    stderr = (
        "Traceback (most recent call last):\n"
        f"  File \"{file_path}\", line 1, in <module>\n"
        "    raise RuntimeError('boom')\n"
        "RuntimeError: boom\n"
        "trace_id=abc123\n"
    )

    async def fake_run(
        *,
        service_id: str,
        content: str,
        port: int,
        env,
        user_id,
        username,
        user_profile,
        fast_mode: bool,
        skip_health_check: bool,
        on_log=None,
    ) -> RunResult:
        return RunResult(
            success=False,
            port=int(port or 0),
            pid=None,
            message="boom",
            logs=[],
            error_category=ErrorCategory.PROCESS_CRASH,
            stderr_output=stderr,
        )

    monkeypatch.setattr(runner_service, "run", fake_run)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/run/stream",
            json={
                "project_id": 1,
                "service_id": service_id,
                "readme_content": _sample_markdown(),
                "port": 12000,
            },
        ) as resp:
            assert resp.status_code == 200
            items = []
            async for line in resp.aiter_lines():
                if not line:
                    continue
                items.append(json.loads(line))

        result_item = next(i for i in items if i.get("type") == "result")
        result_payload = result_item["result"]
        assert result_payload.get("error_report_md")
        assert "### `main.py`" in result_payload["error_report_md"]
