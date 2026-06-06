from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from pactown.iac import (
    PhaseTracker,
    WorkloadConfig,
    WorkloadKind,
    build_sandbox_spec,
    detect_runtime,
    infer_failure_phase,
    load_and_validate_manifest,
    load_plugin_manifest,
    validate_sandbox_manifest,
    write_sandbox_iac,
)
from pactown.markpact_blocks import parse_blocks, extract_target_config, extract_workload_config
from pactown.targets import TargetConfig, TargetPlatform


def test_manifest_includes_target_techstack_validation_and_deploy() -> None:
    readme = """# Electron App

```yaml markpact:target
platform: desktop
framework: electron
app_name: Demo
```

```bash markpact:run
npx electron .
```
"""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        readme_path = root / "README.md"
        readme_path.write_text(readme)
        blocks = parse_blocks(readme_path.read_text())
        target = extract_target_config(blocks)

        spec = build_sandbox_spec(
            service_name="electron-app",
            readme_path=readme_path,
            sandbox_path=root / "sandbox",
            port=None,
            run_cmd="npx electron .",
            is_node=True,
            python_deps=[],
            node_deps=["electron"],
            health_path="/",
            env_keys=[],
            target=target,
            build_cmd="npm run build",
        )

        assert spec["spec"]["workload"]["kind"] == "cli"
        assert spec["spec"]["target"]["platform"] == "desktop"
        assert spec["spec"]["target"]["framework"] == "electron"
        assert spec["spec"]["techstack"]["language"] == "javascript"
        assert "npm" in spec["spec"]["techstack"]["packageManagers"]
        assert spec["spec"]["run"]["buildCommand"] == "npm run build"
        assert len(spec["spec"]["validation"]["phases"]) >= 5
        assert "docker" in spec["spec"]["cicd"]["deploy"]["backends"]
        assert validate_sandbox_manifest(spec) == []


def test_write_sandbox_iac_roundtrip_validation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        readme_path = root / "README.md"
        readme_path.write_text("# svc\n")
        sandbox_path = root / "svc"
        sandbox_path.mkdir()

        written = write_sandbox_iac(
            service_name="svc",
            readme_path=readme_path,
            sandbox_path=sandbox_path,
            port=8000,
            run_cmd="python -m http.server 8000",
            is_node=False,
            python_deps=[],
            node_deps=[],
            health_path="/",
            env_keys=["PORT"],
            target=TargetConfig(platform=TargetPlatform.WEB, framework="flask"),
        )

        assert written["manifest"].exists()
        spec, errors = load_and_validate_manifest(written["manifest"])
        assert errors == []
        assert spec["spec"]["target"]["framework"] == "flask"
        assert (sandbox_path / "Dockerfile").exists()
        assert (sandbox_path / "docker-compose.yaml").exists()


def test_infer_failure_phase_from_manifest_checks() -> None:
    spec = build_sandbox_spec(
        service_name="api",
        readme_path=Path("/tmp/r.md"),
        sandbox_path=Path("/tmp/s"),
        port=8000,
        run_cmd="uvicorn main:app",
        is_node=False,
        python_deps=["fastapi"],
        node_deps=[],
        health_path="/health",
        env_keys=[],
    )
    phase = infer_failure_phase(
        stderr="health check failed: connection refused",
        logs=["timed out waiting for health"],
        manifest=spec,
    )
    assert phase == "health"


def test_infer_failure_phase_deps_without_manifest() -> None:
    phase = infer_failure_phase(stderr="No module named 'flask'", logs=["pip install failed"])
    assert phase == "deps"


def test_phase_tracker_from_manifest() -> None:
    spec = build_sandbox_spec(
        service_name="api",
        readme_path=Path("/tmp/r.md"),
        sandbox_path=Path("/tmp/s"),
        port=8000,
        run_cmd="uvicorn main:app",
        is_node=False,
        python_deps=["fastapi"],
        node_deps=[],
        health_path="/health",
        env_keys=[],
    )
    tracker = PhaseTracker.from_manifest(spec)
    assert "manifest" in tracker.phases
    assert "health" in tracker.phases
    tracker.enter("manifest")
    tracker.complete("manifest")
    assert tracker.summary()["completed"] == ["manifest"]


def test_shell_runtime_from_run_command() -> None:
    spec = build_sandbox_spec(
        service_name="script",
        readme_path=Path("/tmp/r.md"),
        sandbox_path=Path("/tmp/s"),
        port=None,
        run_cmd="./scripts/deploy.sh",
        is_node=False,
        python_deps=[],
        node_deps=[],
        health_path="/",
        env_keys=[],
    )
    assert spec["spec"]["runtime"]["type"] == "shell"
    assert spec["spec"]["workload"]["kind"] == "script"
    assert validate_sandbox_manifest(spec) == []


def test_oci_image_runtime_from_workload_block() -> None:
    workload = WorkloadConfig(kind=WorkloadKind.SERVICE, runtime="oci-image", image="nginx:alpine")
    spec = build_sandbox_spec(
        service_name="proxy",
        readme_path=Path("/tmp/r.md"),
        sandbox_path=Path("/tmp/s"),
        port=8080,
        run_cmd="nginx -g 'daemon off;'",
        is_node=False,
        python_deps=[],
        node_deps=[],
        health_path="/",
        env_keys=[],
        workload=workload,
    )
    assert spec["spec"]["runtime"]["type"] == "oci-image"
    assert spec["spec"]["workload"]["image"] == "nginx:alpine"
    assert spec["spec"]["cicd"]["build"]["oci"]["image"] == "nginx:alpine"
    assert detect_runtime(is_node=False, run_cmd="nginx -g 'daemon off;'", workload=workload).value == "oci-image"


def test_markpact_workload_block_parsed() -> None:
    readme = """# OCI svc

```yaml markpact:workload
kind: job
runtime: shell
```

```bash markpact:run
bash ./run.sh
```
"""
    blocks = parse_blocks(readme)
    wl = extract_workload_config(blocks)
    assert wl is not None
    assert wl.kind == WorkloadKind.JOB
    assert wl.runtime == "shell"


def test_write_shell_iac_dockerfile() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_path = root / "job"
        sandbox_path.mkdir()
        (sandbox_path / "run.sh").write_text("#!/bin/bash\necho ok\n")

        written = write_sandbox_iac(
            service_name="job",
            readme_path=root / "README.md",
            sandbox_path=sandbox_path,
            port=None,
            run_cmd="bash ./run.sh",
            is_node=False,
            python_deps=[],
            node_deps=[],
            health_path="/",
            env_keys=[],
            workload=WorkloadConfig(kind=WorkloadKind.JOB, runtime="shell"),
        )

        dockerfile = written["dockerfile"].read_text()
        assert "debian:bookworm-slim" in dockerfile
        assert "bash ./run.sh" in dockerfile
        spec, errors = load_and_validate_manifest(written["manifest"])
        assert errors == []
        assert spec["spec"]["workload"]["kind"] == "job"
        assert spec["spec"]["runtime"]["type"] == "shell"


def test_write_oci_image_iac_dockerfile() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_path = root / "redis"
        sandbox_path.mkdir()

        written = write_sandbox_iac(
            service_name="redis",
            readme_path=root / "README.md",
            sandbox_path=sandbox_path,
            port=6379,
            run_cmd="redis-server",
            is_node=False,
            python_deps=[],
            node_deps=[],
            health_path="/",
            env_keys=[],
            workload=WorkloadConfig(
                kind=WorkloadKind.SERVICE,
                runtime="oci-image",
                image="redis:7-alpine",
            ),
        )

        dockerfile = written["dockerfile"].read_text()
        assert "FROM redis:7-alpine" in dockerfile
        spec, errors = load_and_validate_manifest(written["manifest"])
        assert errors == []
        assert spec["spec"]["runtime"]["type"] == "oci-image"


def test_detect_runtime_go_from_run_cmd() -> None:
    assert detect_runtime(is_node=False, is_go=False, run_cmd="go run .").value == "go"
    assert detect_runtime(is_node=False, is_go=True, run_cmd="go run .").value == "go"


def test_write_go_iac_dockerfile_and_manifest() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_path = root / "api"
        sandbox_path.mkdir()
        (sandbox_path / "go.mod").write_text("module example.com/api\n\ngo 1.22\n")
        (sandbox_path / "main.go").write_text('package main\nfunc main() {}\n')

        written = write_sandbox_iac(
            service_name="api",
            readme_path=root / "README.md",
            sandbox_path=sandbox_path,
            port=8080,
            run_cmd="go run .",
            is_node=False,
            is_go=True,
            python_deps=[],
            node_deps=[],
            go_deps=["github.com/gin-gonic/gin"],
            health_path="/health",
            env_keys=[],
        )

        dockerfile = written["dockerfile"].read_text()
        assert "golang:1.22-alpine" in dockerfile
        assert "go run ." in dockerfile
        spec, errors = load_and_validate_manifest(written["manifest"])
        assert errors == []
        assert spec["spec"]["runtime"]["type"] == "go"
        assert spec["spec"]["techstack"]["language"] == "go"
        assert "github.com/gin-gonic/gin" in spec["spec"]["dependencies"]["go"]


def test_write_plugin_manifest() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        sandbox_path = root / "ext"
        sandbox_path.mkdir()

        written = write_sandbox_iac(
            service_name="vscode-ext",
            readme_path=root / "README.md",
            sandbox_path=sandbox_path,
            port=None,
            run_cmd="pactown-plugin run --plugin .",
            is_node=True,
            python_deps=[],
            node_deps=[],
            health_path="/",
            env_keys=[],
            workload=WorkloadConfig(
                kind=WorkloadKind.PLUGIN,
                entrypoint="pactown-plugin run --plugin .",
                host_app="vscode",
            ),
        )

        plugin_path = written["plugin"]
        assert plugin_path.name == "pactown.plugin.yaml"
        data, errors = load_plugin_manifest(plugin_path)
        assert errors == []
        assert data["kind"] == "Plugin"
        assert data["spec"]["hostApp"] == "vscode"
        assert data["spec"]["entrypoint"] == "pactown-plugin run --plugin ."
