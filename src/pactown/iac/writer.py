from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..targets import TargetConfig
from .compose import build_single_service_compose, write_single_service_compose
from .dockerfile import write_runtime_dockerfile
from .options import SandboxIacOptions
from .runtime import SandboxRuntime, detect_runtime
from .spec import build_sandbox_spec, write_sandbox_manifest
from .validate import validate_sandbox_manifest
from .plugin import build_plugin_manifest, write_plugin_manifest
from .workload import WorkloadConfig, WorkloadKind


def write_sandbox_iac(
    *,
    service_name: str,
    readme_path: Path,
    sandbox_path: Path,
    port: Optional[int],
    run_cmd: str,
    is_node: bool,
    python_deps: list[str],
    node_deps: list[str],
    go_deps: list[str] | None = None,
    is_go: bool = False,
    health_path: str,
    env_keys: list[str],
    options: Optional[SandboxIacOptions] = None,
    env: Optional[dict[str, str]] = None,
    target: Optional[TargetConfig] = None,
    build_cmd: Optional[str] = None,
    workload: Optional[WorkloadConfig] = None,
) -> dict[str, Path]:
    opts = options or SandboxIacOptions.from_env(env)
    written: dict[str, Path] = {}
    sandbox_runtime = detect_runtime(is_node=is_node, is_go=is_go, run_cmd=run_cmd, workload=workload)

    if opts.write_dockerfile:
        write_runtime_dockerfile(
            sandbox_path=sandbox_path,
            run_cmd=run_cmd,
            runtime=sandbox_runtime,
            workload=workload,
            is_node=is_node,
        )
        written["dockerfile"] = sandbox_path / "Dockerfile"

    if opts.write_compose:
        compose_is_node = sandbox_runtime in (SandboxRuntime.NODE, SandboxRuntime.PYTHON) and is_node
        if sandbox_runtime == SandboxRuntime.SHELL:
            compose_is_node = False
        compose = build_single_service_compose(
            service_name=service_name,
            port=port,
            health_path=health_path,
            is_node=compose_is_node,
        )
        written["compose"] = write_single_service_compose(sandbox_path=sandbox_path, compose=compose)

    if opts.write_manifest:
        spec = build_sandbox_spec(
            service_name=service_name,
            readme_path=readme_path,
            sandbox_path=sandbox_path,
            port=port,
            run_cmd=run_cmd,
            is_node=is_node,
            is_go=is_go,
            python_deps=python_deps,
            node_deps=node_deps,
            go_deps=go_deps or [],
            health_path=health_path,
            env_keys=env_keys,
            target=target,
            build_cmd=build_cmd,
            workload=workload,
        )
        errors = validate_sandbox_manifest(spec)
        if errors:
            raise ValueError(f"invalid sandbox manifest: {'; '.join(errors)}")
        written["manifest"] = write_sandbox_manifest(sandbox_path=sandbox_path, spec=spec)

    if workload and workload.kind == WorkloadKind.PLUGIN:
        plugin_spec = build_plugin_manifest(
            service_name=service_name,
            run_cmd=run_cmd,
            workload=workload,
        )
        written["plugin"] = write_plugin_manifest(sandbox_path=sandbox_path, manifest=plugin_spec)

    return written
