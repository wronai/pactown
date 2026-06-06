from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import yaml


class WorkloadKind(str, Enum):
    """How the sandbox process is meant to run."""

    SERVICE = "service"
    JOB = "job"
    CLI = "cli"
    DAEMON = "daemon"
    BUILD = "build"
    PLUGIN = "plugin"
    SCRIPT = "script"


VALID_WORKLOAD_KINDS = frozenset(k.value for k in WorkloadKind)
VALID_RESTART_POLICIES = frozenset({"always", "on-failure", "never", "unless-stopped"})


@dataclass
class WorkloadConfig:
    kind: WorkloadKind = WorkloadKind.SERVICE
    runtime: Optional[str] = None
    image: Optional[str] = None
    entrypoint: Optional[str] = None
    args: list[str] = field(default_factory=list)
    restart_policy: str = "unless-stopped"
    schedule: Optional[str] = None
    host_app: Optional[str] = None

    @classmethod
    def from_yaml_body(cls, body: str) -> WorkloadConfig:
        try:
            data = yaml.safe_load(body)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkloadConfig:
        kind_raw = str(data.get("kind", "service")).strip().lower()
        try:
            kind = WorkloadKind(kind_raw)
        except ValueError:
            kind = WorkloadKind.SERVICE

        runtime = data.get("runtime")
        if runtime is not None:
            runtime = str(runtime).strip().lower()

        image = data.get("image")
        if image is not None:
            image = str(image).strip()

        entrypoint = data.get("entrypoint")
        if entrypoint is not None:
            entrypoint = str(entrypoint).strip()

        raw_args = data.get("args", [])
        if isinstance(raw_args, str):
            args = [raw_args]
        elif isinstance(raw_args, list):
            args = [str(a) for a in raw_args]
        else:
            args = []

        restart = str(data.get("restart_policy", data.get("restartPolicy", "unless-stopped"))).strip().lower()
        if restart not in VALID_RESTART_POLICIES:
            restart = "unless-stopped"

        schedule = data.get("schedule")
        if schedule is not None:
            schedule = str(schedule).strip() or None

        host_app = data.get("host_app", data.get("hostApp"))
        if host_app is not None:
            host_app = str(host_app).strip() or None

        return cls(
            kind=kind,
            runtime=runtime,
            image=image,
            entrypoint=entrypoint,
            args=args,
            restart_policy=restart,
            schedule=schedule,
            host_app=host_app,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value}
        if self.runtime:
            out["runtime"] = self.runtime
        if self.image:
            out["image"] = self.image
        if self.entrypoint:
            out["entrypoint"] = self.entrypoint
        if self.args:
            out["args"] = list(self.args)
        if self.restart_policy != "unless-stopped":
            out["restartPolicy"] = self.restart_policy
        if self.schedule:
            out["schedule"] = self.schedule
        if self.host_app:
            out["hostApp"] = self.host_app
        return out


def infer_workload_kind(
    *,
    port: Optional[int],
    run_cmd: str,
    build_cmd: Optional[str] = None,
    explicit: Optional[WorkloadConfig] = None,
) -> WorkloadKind:
    if explicit is not None:
        return explicit.kind

    if build_cmd and not (run_cmd or "").strip():
        return WorkloadKind.BUILD

    rc = (run_cmd or "").strip().lower()
    if rc.startswith("pactown-plugin") or " --plugin" in f" {rc} ":
        return WorkloadKind.PLUGIN

    if port is None:
        if rc.endswith(".sh") or rc.startswith("./") or rc.startswith("bash ") or rc.startswith("sh "):
            return WorkloadKind.SCRIPT
        if " --once" in f" {rc} " or rc.startswith("python -c") or rc.startswith("node -e"):
            return WorkloadKind.JOB
        return WorkloadKind.CLI

    return WorkloadKind.SERVICE
