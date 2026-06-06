from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from .workload import WorkloadConfig


class SandboxRuntime(str, Enum):
    PYTHON = "python"
    NODE = "node"
    GO = "go"
    SHELL = "shell"
    OCI_IMAGE = "oci-image"


VALID_RUNTIME_TYPES = frozenset(r.value for r in SandboxRuntime)

_SHELL_CMD_PREFIXES = ("./", "bash ", "sh ", "/bin/bash", "/bin/sh", "exec ")
_GO_CMD_PREFIXES = ("go run", "go build", "go test", "go install")


def runtime_type(*, is_node: bool, is_go: bool = False) -> str:
    if is_go:
        return SandboxRuntime.GO.value
    return SandboxRuntime.NODE.value if is_node else SandboxRuntime.PYTHON.value


def detect_runtime(
    *,
    is_node: bool,
    is_go: bool = False,
    run_cmd: str,
    workload: Optional[WorkloadConfig] = None,
) -> SandboxRuntime:
    if workload is not None:
        if workload.runtime and workload.runtime in VALID_RUNTIME_TYPES:
            return SandboxRuntime(workload.runtime)
        if workload.image:
            return SandboxRuntime.OCI_IMAGE

    if is_go:
        return SandboxRuntime.GO

    rc = (run_cmd or "").strip().lower()
    if rc.startswith(_GO_CMD_PREFIXES):
        return SandboxRuntime.GO
    if rc.startswith(_SHELL_CMD_PREFIXES):
        return SandboxRuntime.SHELL
    if re.match(r"^[a-z0-9._/-]+:[a-z0-9._-]+$", rc) and " " not in rc.strip():
        return SandboxRuntime.OCI_IMAGE

    return SandboxRuntime.NODE if is_node else SandboxRuntime.PYTHON


def default_base_image(*, runtime: SandboxRuntime | str, is_node: bool = False) -> str:
    r = runtime if isinstance(runtime, SandboxRuntime) else SandboxRuntime(runtime)
    if r == SandboxRuntime.OCI_IMAGE:
        return "nginx:alpine"
    if r == SandboxRuntime.SHELL:
        return "debian:bookworm-slim"
    if r == SandboxRuntime.GO:
        return "golang:1.22-alpine"
    if r == SandboxRuntime.NODE:
        return "node:20-slim"
    return "python:3.12-slim"


def resolve_oci_image(
    *,
    run_cmd: str,
    workload: Optional[WorkloadConfig] = None,
) -> Optional[str]:
    if workload and workload.image:
        return workload.image

    rc = (run_cmd or "").strip()
    if re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*:[a-zA-Z0-9][a-zA-Z0-9._-]*$", rc):
        return rc
    return None
