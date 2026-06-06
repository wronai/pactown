from __future__ import annotations

from pathlib import Path

from tests.conftest import async_test

from pactown.service_runner import ServiceRunner


_JOB_README = """# One-shot job

```text markpact:file path=run.sh
#!/bin/bash
echo hello
```

```bash markpact:run
bash ./run.sh
```
"""


@async_test
async def test_run_job_from_content_success(tmp_path: Path, monkeypatch) -> None:
    runner = ServiceRunner(str(tmp_path))
    sandbox = tmp_path / "service_job1"

    def fake_run_job_sync(*_args, **_kwargs):
        return {
            "exit_code": 0,
            "stdout": "hello\n",
            "stderr": "",
            "sandbox_path": str(sandbox),
            "timed_out": False,
        }

    monkeypatch.setattr(runner.sandbox_manager, "run_job_sync", fake_run_job_sync)

    result = await runner.run_job_from_content("job1", _JOB_README)

    assert result.success is True
    assert result.exit_code == 0
    assert result.sandbox_path == str(sandbox)
    assert any("hello" in line for line in result.logs)


@async_test
async def test_run_job_from_content_nonzero_exit(tmp_path: Path, monkeypatch) -> None:
    runner = ServiceRunner(str(tmp_path))

    def fake_run_job_sync(*_args, **_kwargs):
        return {
            "exit_code": 2,
            "stdout": "",
            "stderr": "boom",
            "sandbox_path": str(tmp_path / "svc"),
            "timed_out": False,
        }

    monkeypatch.setattr(runner.sandbox_manager, "run_job_sync", fake_run_job_sync)

    result = await runner.run_job_from_content("job2", _JOB_README)

    assert result.success is False
    assert result.exit_code == 2
    assert result.failure_phase == "run"
