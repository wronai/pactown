from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SandboxIacOptions:
    write_manifest: bool = True
    write_dockerfile: bool = True
    write_compose: bool = True

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> SandboxIacOptions:
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
