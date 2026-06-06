from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from ..targets import TargetConfig, TargetPlatform, infer_target_from_deps
from .runtime import SandboxRuntime, default_base_image, detect_runtime, resolve_oci_image
from .workload import WorkloadConfig, WorkloadKind, infer_workload_kind

API_VERSION = "pactown.dev/v1alpha1"
DEPLOY_BACKENDS = ("docker", "compose", "ansible", "quadlet", "kubernetes", "podman")


def _clean_deps(items: list[str]) -> list[str]:
    return [d for d in items if d and str(d).strip()]


def _target_section(target: Optional[TargetConfig]) -> dict[str, Any]:
    if target is None:
        return {"platform": TargetPlatform.WEB.value}
    section: dict[str, Any] = {"platform": target.platform.value}
    if target.framework:
        section["framework"] = target.framework
    if target.targets:
        section["targets"] = list(target.targets)
    if target.app_name:
        section["appName"] = target.app_name
    if target.app_id:
        section["appId"] = target.app_id
    if target.app_version:
        section["appVersion"] = target.app_version
    return section


def _workload_section(
    *,
    workload: WorkloadConfig,
    explicit_workload: Optional[WorkloadConfig],
    port: Optional[int],
    run_cmd: str,
    build_cmd: Optional[str],
) -> dict[str, Any]:
    kind = infer_workload_kind(
        port=port,
        run_cmd=run_cmd,
        build_cmd=build_cmd,
        explicit=explicit_workload,
    )
    section = workload.to_dict()
    section["kind"] = kind.value
    return section


def _techstack_section(
    *,
    sandbox_runtime: SandboxRuntime,
    python_deps: list[str],
    node_deps: list[str],
    go_deps: list[str],
    target: Optional[TargetConfig],
    workload: Optional[WorkloadConfig],
) -> dict[str, Any]:
    language = "shell"
    if sandbox_runtime == SandboxRuntime.PYTHON:
        language = "python"
    elif sandbox_runtime == SandboxRuntime.NODE:
        language = "javascript"
    elif sandbox_runtime == SandboxRuntime.OCI_IMAGE:
        language = "container"
    elif sandbox_runtime == SandboxRuntime.GO:
        language = "go"
    if target and target.framework_meta:
        language = target.framework_meta.language or language

    package_managers: list[str] = []
    if python_deps:
        package_managers.append("pip")
    if node_deps:
        package_managers.append("npm")
    if go_deps or sandbox_runtime == SandboxRuntime.GO:
        package_managers.append("go")
    if sandbox_runtime == SandboxRuntime.SHELL and "apt" not in package_managers:
        package_managers.append("shell")

    runtimes: dict[str, Optional[str]] = {
        "python": "3.12" if sandbox_runtime == SandboxRuntime.PYTHON else None,
        "node": "20" if sandbox_runtime == SandboxRuntime.NODE else None,
        "go": "1.22" if sandbox_runtime == SandboxRuntime.GO else None,
        "shell": "bash" if sandbox_runtime == SandboxRuntime.SHELL else None,
        "oci": resolve_oci_image(run_cmd="", workload=workload) if sandbox_runtime == SandboxRuntime.OCI_IMAGE else None,
    }

    return {
        "language": language,
        "runtime": sandbox_runtime.value,
        "runtimes": runtimes,
        "packageManagers": package_managers,
    }


def _cicd_section(
    *,
    sandbox_runtime: SandboxRuntime,
    is_node: bool,
    port: Optional[int],
    run_cmd: str,
    build_cmd: Optional[str],
    explicit_workload: Optional[WorkloadConfig],
) -> dict[str, Any]:
    kind = infer_workload_kind(port=port, run_cmd=run_cmd, build_cmd=build_cmd, explicit=explicit_workload)
    stages = ["scaffold", "deps", "run"]
    if kind == WorkloadKind.BUILD:
        stages = ["scaffold", "deps", "build"]
    elif port is not None and kind == WorkloadKind.SERVICE:
        stages.append("health")
    stages.append("deploy")

    base = default_base_image(runtime=sandbox_runtime, is_node=is_node)
    build_section: dict[str, Any] = {
        "docker": {
            "context": ".",
            "dockerfile": "Dockerfile",
            "baseImage": base,
        },
    }
    if sandbox_runtime == SandboxRuntime.OCI_IMAGE:
        image = resolve_oci_image(run_cmd=run_cmd, workload=explicit_workload)
        if image:
            build_section["oci"] = {"image": image}

    return {
        "stages": stages,
        "build": build_section,
        "run": {
            "compose": {
                "file": "docker-compose.yaml",
            },
        },
        "deploy": {
            "backends": list(DEPLOY_BACKENDS),
        },
    }


def _validation_phases(
    *,
    sandbox_runtime: SandboxRuntime,
    port: Optional[int],
    health_path: str,
    python_deps: list[str],
    node_deps: list[str],
    go_deps: list[str],
    run_cmd: str,
    build_cmd: Optional[str],
    explicit_workload: Optional[WorkloadConfig],
) -> list[dict[str, Any]]:
    kind = infer_workload_kind(port=port, run_cmd=run_cmd, build_cmd=build_cmd, explicit=explicit_workload)

    phases: list[dict[str, Any]] = [
        {
            "name": "manifest",
            "description": "Validate pactown.sandbox.yaml structure",
            "checks": ["apiVersion", "kind", "metadata.name", "spec.runtime.type", "spec.workload.kind"],
        },
        {
            "name": "scaffold",
            "description": "Verify sandbox files were materialized from README",
            "checks": ["artifacts.sandboxPath"],
        },
    ]

    if sandbox_runtime == SandboxRuntime.OCI_IMAGE:
        phases.append(
            {
                "name": "deps",
                "description": "OCI image pull / local context",
                "checks": ["cicd.build.oci.image", "artifacts.dockerfile"],
            }
        )
    elif sandbox_runtime == SandboxRuntime.SHELL:
        phases.append(
            {
                "name": "deps",
                "description": "Shell runtime – optional system packages in image build",
                "checks": ["run.command", "artifacts.dockerfile"],
            }
        )
    elif sandbox_runtime == SandboxRuntime.GO:
        phases.append(
            {
                "name": "deps",
                "description": "Go modules download (go mod tidy)",
                "checks": ["artifacts.hasGoMod", "dependencies.go"],
            }
        )
    else:
        phases.append(
            {
                "name": "deps",
                "description": "Install runtime dependencies",
                "checks": (
                    ["artifacts.hasPackageJson", "dependencies.node"]
                    if sandbox_runtime == SandboxRuntime.NODE
                    else ["artifacts.hasRequirementsTxt", "dependencies.python"]
                ),
            }
        )

    if kind == WorkloadKind.BUILD:
        phases.append(
            {
                "name": "build",
                "description": "One-shot artifact build",
                "checks": ["run.buildCommand"],
            }
        )
    else:
        phases.append(
            {
                "name": "run",
                "description": "Start process",
                "checks": ["run.command"],
            }
        )

    if port is not None and kind == WorkloadKind.SERVICE:
        phases.append(
            {
                "name": "health",
                "description": f"HTTP health probe on {health_path}",
                "checks": ["health.path", "run.port", "cicd.run.compose"],
            }
        )

    if python_deps or node_deps or go_deps:
        phases[1]["checks"].append("dependencies")

    phases.append(
        {
            "name": "deploy",
            "description": "Optional container/deploy backend execution",
            "checks": ["cicd.deploy.backends", "artifacts.dockerfile", "artifacts.compose"],
        }
    )
    return phases


def resolve_target_config(
    *,
    blocks_target: Optional[TargetConfig],
    python_deps: list[str],
    node_deps: list[str],
) -> TargetConfig:
    if blocks_target is not None:
        return blocks_target
    all_deps = list(python_deps) + list(node_deps)
    platform = infer_target_from_deps(all_deps)
    return TargetConfig(platform=platform)


def build_sandbox_spec(
    *,
    service_name: str,
    readme_path: Path,
    sandbox_path: Path,
    port: Optional[int],
    run_cmd: str,
    is_node: bool,
    python_deps: list[str],
    node_deps: list[str],
    health_path: str,
    is_go: bool = False,
    go_deps: list[str] | None = None,
    env_keys: list[str],
    target: Optional[TargetConfig] = None,
    build_cmd: Optional[str] = None,
    workload: Optional[WorkloadConfig] = None,
) -> dict[str, Any]:
    resolved_workload = workload or WorkloadConfig()
    go_deps = go_deps or []
    sandbox_runtime = detect_runtime(is_node=is_node, is_go=is_go, run_cmd=run_cmd, workload=workload)
    now = datetime.now(UTC).isoformat()
    resolved_target = resolve_target_config(
        blocks_target=target,
        python_deps=python_deps,
        node_deps=node_deps,
    )
    safe_env_keys = sorted({str(k) for k in (env_keys or []) if k and str(k).strip()})
    health = (health_path or "/").strip() or "/"
    py_deps = _clean_deps(python_deps)
    nd_deps = _clean_deps(node_deps)
    go_deps_clean = _clean_deps(go_deps)

    run_section: dict[str, Any] = {
        "command": (run_cmd or "").strip(),
        "port": int(port) if port is not None else None,
        "portEnv": "MARKPACT_PORT",
    }
    if build_cmd:
        run_section["buildCommand"] = build_cmd.strip()

    return {
        "apiVersion": API_VERSION,
        "kind": "Sandbox",
        "metadata": {
            "name": service_name,
            "createdAt": now,
            "sourceReadme": str(readme_path),
        },
        "spec": {
            "workload": _workload_section(
                workload=resolved_workload,
                explicit_workload=workload,
                port=port,
                run_cmd=run_cmd,
                build_cmd=build_cmd,
            ),
            "target": _target_section(resolved_target),
            "techstack": _techstack_section(
                sandbox_runtime=sandbox_runtime,
                python_deps=py_deps,
                node_deps=nd_deps,
                go_deps=go_deps_clean,
                target=resolved_target,
                workload=workload,
            ),
            "runtime": {
                "type": sandbox_runtime.value,
            },
            "dependencies": {
                "python": py_deps,
                "node": nd_deps,
                "go": go_deps_clean,
            },
            "run": run_section,
            "health": {
                "path": health,
            },
            "artifacts": {
                "sandboxPath": str(sandbox_path),
                "hasRequirementsTxt": (sandbox_path / "requirements.txt").exists(),
                "hasPackageJson": (sandbox_path / "package.json").exists(),
                "hasGoMod": (sandbox_path / "go.mod").exists(),
                "dockerfile": "Dockerfile" if (sandbox_path / "Dockerfile").exists() else None,
                "compose": "docker-compose.yaml" if (sandbox_path / "docker-compose.yaml").exists() else None,
                "manifest": "pactown.sandbox.yaml",
            },
            "env": {
                "keys": safe_env_keys,
                "dotenv": ".env",
            },
            "cicd": _cicd_section(
                sandbox_runtime=sandbox_runtime,
                is_node=is_node,
                port=port,
                run_cmd=run_cmd,
                build_cmd=build_cmd,
                explicit_workload=workload,
            ),
            "validation": {
                "phases": _validation_phases(
                    sandbox_runtime=sandbox_runtime,
                    port=port,
                    health_path=health,
                    python_deps=py_deps,
                    node_deps=nd_deps,
                    go_deps=go_deps_clean,
                    run_cmd=run_cmd,
                    build_cmd=build_cmd,
                    explicit_workload=workload,
                ),
            },
        },
    }


def write_sandbox_manifest(*, sandbox_path: Path, spec: dict[str, Any]) -> Path:
    out = sandbox_path / "pactown.sandbox.yaml"
    out.write_text(yaml.safe_dump(spec, sort_keys=False))
    return out
