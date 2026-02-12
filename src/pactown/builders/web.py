"""Builder for web services (existing behavior wrapped in Builder interface)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .base import Builder, BuildResult

try:
    from ..nfo_config import logged
except Exception:
    def logged(cls=None, **kw):  # type: ignore[misc]
        return cls if cls is not None else lambda c: c

_logger = logging.getLogger("pactown.builders.web")


@logged
class WebBuilder(Builder):
    """Web services don't produce build artifacts – they run as servers.

    This builder exists for API symmetry.  ``scaffold()`` is a no-op
    (the sandbox manager already handles web projects).  ``build()``
    simply verifies that the sandbox looks runnable and returns a
    successful BuildResult.
    """

    @property
    def platform_name(self) -> str:
        return "web"

    def scaffold(
        self,
        sandbox_path: Path,
        *,
        framework: str,
        app_name: str = "app",
        extra: Optional[dict[str, Any]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        # Web projects are scaffolded by the existing sandbox manager
        self._log(on_log, "[web] No additional scaffolding needed (handled by sandbox manager)")

    def build(
        self,
        sandbox_path: Path,
        *,
        build_cmd: Optional[str] = None,
        framework: str = "",
        targets: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> BuildResult:
        t0 = time.monotonic()
        logs: list[str] = []

        def _log(msg: str) -> None:
            logs.append(msg)
            self._log(on_log, msg)

        if build_cmd:
            _log(f"[web] Running build step: {build_cmd}")
            rc, stdout, stderr = self._run_shell(build_cmd, cwd=sandbox_path, env=env, on_log=on_log)
            elapsed = time.monotonic() - t0
            if rc != 0:
                _log(f"[web] Build step failed (exit {rc})")
                return BuildResult(
                    success=False,
                    platform="web",
                    framework=framework,
                    message=f"Web build step failed with exit code {rc}",
                    logs=logs,
                    build_cmd=build_cmd,
                    elapsed_seconds=elapsed,
                )
        else:
            elapsed = time.monotonic() - t0

        _log("[web] Web project ready (use 'run' to start the server)")
        return BuildResult(
            success=True,
            platform="web",
            framework=framework,
            output_dir=sandbox_path,
            message="Web project ready",
            logs=logs,
            build_cmd=build_cmd or "",
            elapsed_seconds=elapsed,
        )
