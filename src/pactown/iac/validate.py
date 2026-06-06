from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from .spec import API_VERSION
from .workload import VALID_WORKLOAD_KINDS
from .runtime import VALID_RUNTIME_TYPES

_REQUIRED_ROOT = ("apiVersion", "kind", "metadata", "spec")
_REQUIRED_METADATA = ("name",)
_REQUIRED_SPEC = ("workload", "runtime", "run", "health", "dependencies", "cicd", "validation")


def _get_nested(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_sandbox_manifest(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if not isinstance(spec, dict):
        return ["manifest must be a mapping"]

    for key in _REQUIRED_ROOT:
        if key not in spec:
            errors.append(f"missing required field: {key}")

    if spec.get("apiVersion") != API_VERSION:
        errors.append(f"apiVersion must be {API_VERSION!r}")

    if spec.get("kind") != "Sandbox":
        errors.append("kind must be 'Sandbox'")

    metadata = spec.get("metadata")
    if isinstance(metadata, dict):
        for key in _REQUIRED_METADATA:
            if key not in metadata:
                errors.append(f"missing metadata.{key}")
    else:
        errors.append("metadata must be a mapping")

    body = spec.get("spec")
    if not isinstance(body, dict):
        errors.append("spec must be a mapping")
        return errors

    for key in _REQUIRED_SPEC:
        if key not in body:
            errors.append(f"missing spec.{key}")

    workload = body.get("workload")
    if isinstance(workload, dict):
        kind = workload.get("kind")
        if kind not in VALID_WORKLOAD_KINDS:
            errors.append(f"spec.workload.kind must be one of {sorted(VALID_WORKLOAD_KINDS)}")
        if workload.get("runtime") and workload["runtime"] not in VALID_RUNTIME_TYPES:
            errors.append(f"spec.workload.runtime must be one of {sorted(VALID_RUNTIME_TYPES)}")
    else:
        errors.append("spec.workload must be a mapping")

    runtime = body.get("runtime")
    if isinstance(runtime, dict):
        rtype = runtime.get("type")
        if rtype not in VALID_RUNTIME_TYPES:
            errors.append(f"spec.runtime.type must be one of {sorted(VALID_RUNTIME_TYPES)}")
    else:
        errors.append("spec.runtime must be a mapping")

    run = body.get("run")
    if isinstance(run, dict):
        has_cmd = bool(str(run.get("command") or "").strip())
        has_build = bool(str(run.get("buildCommand") or "").strip())
        workload_kind = _get_nested(body, "workload.kind")
        if workload_kind == "build":
            if not has_build and not has_cmd:
                errors.append("spec.run.buildCommand or spec.run.command required for build workload")
        elif not has_cmd:
            errors.append("spec.run.command must be non-empty")
    else:
        errors.append("spec.run must be a mapping")

    validation = body.get("validation")
    if isinstance(validation, dict):
        phases = validation.get("phases")
        if not isinstance(phases, list) or not phases:
            errors.append("spec.validation.phases must be a non-empty list")
    else:
        errors.append("spec.validation must be a mapping")

    cicd = body.get("cicd")
    if isinstance(cicd, dict):
        deploy = cicd.get("deploy")
        if isinstance(deploy, dict):
            backends = deploy.get("backends")
            if not isinstance(backends, list) or not backends:
                errors.append("spec.cicd.deploy.backends must be a non-empty list")
        else:
            errors.append("spec.cicd.deploy must be a mapping")

    return errors


def load_sandbox_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a mapping")
    return data


def load_and_validate_manifest(path: Path) -> tuple[dict[str, Any], list[str]]:
    spec = load_sandbox_manifest(path)
    return spec, validate_sandbox_manifest(spec)


def infer_failure_phase(
    *,
    stderr: str = "",
    logs: Optional[list[str]] = None,
    manifest: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    combined = "\n".join([stderr or "", "\n".join(logs or [])]).lower()

    phase_patterns: list[tuple[str, tuple[str, ...]]] = [
        ("health", ("health check", "healthcheck", "connection refused", "timed out waiting")),
        ("deps", ("pip install", "npm install", "no module named", "cannot find module", "requirements.txt", "image pull", "pull access denied")),
        ("build", ("docker build", "dockerfile", "build failed", "electron-builder", "pyinstaller")),
        ("run", ("uvicorn", "gunicorn", "node server", "address already in use", "errno", "/bin/bash", "/bin/sh")),
        ("deploy", ("ansible", "quadlet", "kubectl", "podman", "systemctl")),
        ("scaffold", ("markpact", "write file", "sandbox path")),
        ("manifest", ("pactown.sandbox.yaml", "apiversion", "invalid manifest")),
    ]

    if manifest:
        phases = _get_nested(manifest, "spec.validation.phases")
        if isinstance(phases, list):
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                name = str(phase.get("name") or "").strip().lower()
                if not name:
                    continue
                checks = phase.get("checks") or []
                for check in checks:
                    token = str(check).lower()
                    if token and token in combined:
                        return name

    for phase, patterns in phase_patterns:
        if any(p in combined for p in patterns):
            return phase

    return None
