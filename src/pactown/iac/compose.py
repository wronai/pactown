from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml


def build_single_service_compose(
    *,
    service_name: str,
    port: Optional[int],
    health_path: str,
    is_node: bool,
) -> dict[str, Any]:
    health_path = (health_path or "/").strip() or "/"
    if not health_path.startswith("/"):
        health_path = f"/{health_path}"

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
