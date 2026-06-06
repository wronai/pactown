from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .workload import WorkloadConfig

PLUGIN_API_VERSION = "pactown.dev/v1alpha1"
PLUGIN_MANIFEST_NAME = "pactown.plugin.yaml"
VALID_PLUGIN_PERMISSIONS = frozenset(
    {
        "sandbox.read",
        "sandbox.write",
        "network.outbound",
        "filesystem.read",
        "filesystem.write",
        "process.spawn",
    }
)


@dataclass
class PluginManifest:
    name: str
    version: str = "0.1.0"
    entrypoint: str = ""
    host_app: Optional[str] = None
    permissions: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "version": self.version,
            "entrypoint": self.entrypoint,
            "permissions": list(self.permissions),
            "hooks": list(self.hooks),
        }
        if self.host_app:
            spec["hostApp"] = self.host_app
        return {
            "apiVersion": PLUGIN_API_VERSION,
            "kind": "Plugin",
            "metadata": {"name": self.name},
            "spec": spec,
        }


def build_plugin_manifest(
    *,
    service_name: str,
    run_cmd: str,
    workload: Optional[WorkloadConfig] = None,
    version: str = "0.1.0",
) -> dict[str, Any]:
    entrypoint = (workload.entrypoint if workload and workload.entrypoint else run_cmd).strip()
    host_app = workload.host_app if workload else None
    return PluginManifest(
        name=service_name,
        version=version,
        entrypoint=entrypoint,
        host_app=host_app,
        permissions=["sandbox.read", "process.spawn"],
        hooks=[],
    ).to_dict()


def validate_plugin_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if data.get("apiVersion") != PLUGIN_API_VERSION:
        errors.append(f"apiVersion must be {PLUGIN_API_VERSION!r}")
    if data.get("kind") != "Plugin":
        errors.append("kind must be 'Plugin'")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("name"):
        errors.append("metadata.name is required")

    spec = data.get("spec")
    if not isinstance(spec, dict):
        errors.append("spec must be a mapping")
        return errors

    if not str(spec.get("entrypoint") or "").strip():
        errors.append("spec.entrypoint is required")

    perms = spec.get("permissions", [])
    if perms is not None:
        if not isinstance(perms, list):
            errors.append("spec.permissions must be a list")
        else:
            for p in perms:
                if str(p) not in VALID_PLUGIN_PERMISSIONS:
                    errors.append(f"unknown permission: {p}")

    return errors


def write_plugin_manifest(*, sandbox_path: Path, manifest: dict[str, Any]) -> Path:
    errors = validate_plugin_manifest(manifest)
    if errors:
        raise ValueError(f"invalid plugin manifest: {'; '.join(errors)}")
    out = sandbox_path / PLUGIN_MANIFEST_NAME
    out.write_text(yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False))
    return out


def load_plugin_manifest(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, [f"missing {PLUGIN_MANIFEST_NAME}"]
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        return {}, [f"failed to parse plugin manifest: {e}"]
    if not isinstance(data, dict):
        return {}, ["plugin manifest must be a mapping"]
    return data, validate_plugin_manifest(data)
