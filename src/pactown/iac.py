from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import os
import yaml

from .deploy.base import DeploymentConfig
from .deploy.docker import DockerBackend


@dataclass
class SandboxIacOptions:
    write_manifest: bool = True
    write_dockerfile: bool = True
    write_compose: bool = True

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "SandboxIacOptions":
        src = env or os.environ

        def truthy(key: str, default: bool) -> bool:
            raw = src.get(key)
            if raw is None:
                return default
            v = str(raw).strip().lower()
            if v in {"1", "true", "yes", "y", "on"}:
                return True
            if v in {"0", "false", "no", "n", "off"}:
                return False
            return default

        enabled = truthy("PACTOWN_WRITE_IAC", True)
        return cls(
            write_manifest=enabled and truthy("PACTOWN_WRITE_IAC_MANIFEST", True),
            write_dockerfile=enabled and truthy("PACTOWN_WRITE_IAC_DOCKERFILE", True),
            write_compose=enabled and truthy("PACTOWN_WRITE_IAC_COMPOSE", True),
        )


def _runtime_type(*, is_node: bool) -> str:
    return "node" if is_node else "python"


def _default_base_image(*, is_node: bool) -> str:
    return "node:20-slim" if is_node else "python:3.12-slim"


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
    env_keys: list[str],
) -> dict[str, Any]:
    runtime = _runtime_type(is_node=is_node)
    now = datetime.now(UTC).isoformat()

    safe_env_keys = sorted({str(k) for k in (env_keys or []) if k and str(k).strip()})

    spec: dict[str, Any] = {
        "apiVersion": "pactown.dev/v1alpha1",
        "kind": "Sandbox",
        "metadata": {
            "name": service_name,
            "createdAt": now,
            "sourceReadme": str(readme_path),
        },
        "spec": {
            "runtime": {
                "type": runtime,
            },
            "dependencies": {
                "python": [d for d in python_deps if d and str(d).strip()],
                "node": [d for d in node_deps if d and str(d).strip()],
            },
            "run": {
                "command": (run_cmd or "").strip(),
                "port": int(port) if port is not None else None,
                "portEnv": "MARKPACT_PORT",
            },
            "health": {
                "path": (health_path or "/").strip() or "/",
            },
            "artifacts": {
                "sandboxPath": str(sandbox_path),
                "hasRequirementsTxt": (sandbox_path / "requirements.txt").exists(),
                "hasPackageJson": (sandbox_path / "package.json").exists(),
                "dockerfile": "Dockerfile" if (sandbox_path / "Dockerfile").exists() else None,
                "compose": "docker-compose.yaml" if (sandbox_path / "docker-compose.yaml").exists() else None,
            },
            "env": {
                "keys": safe_env_keys,
                "dotenv": ".env",
            },
            "cicd": {
                "build": {
                    "docker": {
                        "context": ".",
                        "dockerfile": "Dockerfile",
                        "baseImage": _default_base_image(is_node=is_node),
                    },
                },
                "run": {
                    "compose": {
                        "file": "docker-compose.yaml",
                    },
                },
            },
        },
    }

    return spec


def write_sandbox_manifest(*, sandbox_path: Path, spec: dict[str, Any]) -> Path:
    out = sandbox_path / "pactown.sandbox.yaml"
    out.write_text(yaml.safe_dump(spec, sort_keys=False))
    return out


def build_single_service_compose(
    *,
    service_name: str,
    port: Optional[int],
    health_path: str,
    is_node: bool,
) -> dict[str, Any]:
    health_path = (health_path or "/").strip() or "/"
    if not health_path.startswith("/"):
        health_path = "/" + health_path

    svc: dict[str, Any] = {
        "build": {"context": ".", "dockerfile": "Dockerfile"},
        "container_name": service_name,
        "restart": "unless-stopped",
        "env_file": [".env"],
        "environment": {
            "PORT": str(port) if port is not None else "",
            "MARKPACT_PORT": str(port) if port is not None else "",
        },
    }

    if port is not None:
        svc["ports"] = [f"{port}:{port}"]

    if is_node:
        svc["healthcheck"] = {
            "test": [
                "CMD",
                "node",
                "-e",
                (
                    "const http=require('http');"
                    "const port=process.env.MARKPACT_PORT||process.env.PORT||3000;"
                    f"http.get('http://localhost:'+port+'{health_path}',res=>process.exit(res.statusCode<400?0:1))"
                    ".on('error',()=>process.exit(1));"
                ),
            ],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "10s",
        }
    else:
        svc["healthcheck"] = {
            "test": [
                "CMD",
                "python",
                "-c",
                (
                    "import os,urllib.request; "
                    "port=os.environ.get('MARKPACT_PORT') or os.environ.get('PORT','8000'); "
                    f"urllib.request.urlopen('http://localhost:%s{health_path}' % port, timeout=5)"
                ),
            ],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "10s",
        }

    return {
        "version": "3.8",
        "services": {
            "app": svc,
        },
    }


def write_single_service_compose(*, sandbox_path: Path, compose: dict[str, Any]) -> Path:
    out = sandbox_path / "docker-compose.yaml"
    out.write_text(yaml.safe_dump(compose, sort_keys=False))
    return out


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
    health_path: str,
    env_keys: list[str],
    options: Optional[SandboxIacOptions] = None,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Path]:
    opts = options or SandboxIacOptions.from_env(env)
    written: dict[str, Path] = {}

    if opts.write_dockerfile:
        backend = DockerBackend(DeploymentConfig.for_development())
        backend.generate_dockerfile(
            service_name=service_name,
            sandbox_path=sandbox_path,
            base_image=_default_base_image(is_node=is_node),
            run_cmd=run_cmd,
        )
        written["dockerfile"] = sandbox_path / "Dockerfile"

    if opts.write_compose:
        compose = build_single_service_compose(
            service_name=service_name,
            port=port,
            health_path=health_path,
            is_node=is_node,
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
            python_deps=python_deps,
            node_deps=node_deps,
            health_path=health_path,
            env_keys=env_keys,
        )
        written["manifest"] = write_sandbox_manifest(sandbox_path=sandbox_path, spec=spec)

    return written
