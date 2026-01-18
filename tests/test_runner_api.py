import httpx
import pytest

from pactown.runner_api import RunnerApiSettings, RunnerService, create_runner_api


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
