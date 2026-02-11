"""Base builder interface for all target platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


class BuildError(Exception):
    """Raised when a build operation fails."""


@dataclass
class BuildResult:
    """Result of a build operation."""

    success: bool
    platform: str  # web | desktop | mobile
    framework: str = ""
    artifacts: list[Path] = field(default_factory=list)
    output_dir: Optional[Path] = None
    message: str = ""
    logs: list[str] = field(default_factory=list)
    build_cmd: str = ""
    elapsed_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Builder(ABC):
    """Abstract base for platform builders."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (web, desktop, mobile)."""

    @abstractmethod
    def scaffold(
        self,
        sandbox_path: Path,
        *,
        framework: str,
        app_name: str = "app",
        extra: Optional[dict[str, Any]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Generate boilerplate / config files required by the framework.

        Called *after* markpact files are written to the sandbox but
        *before* dependencies are installed or the build command runs.
        """

    @abstractmethod
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
        """Run the build and return a BuildResult with artifact paths."""

    # ------------------------------------------------------------------
    # Helpers shared by all builders
    # ------------------------------------------------------------------

    @staticmethod
    def _log(on_log: Optional[Callable[[str], None]], msg: str) -> None:
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    @staticmethod
    def _run_shell(
        cmd: str,
        *,
        cwd: Path,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        timeout: int = 600,
    ) -> tuple[int, str, str]:
        """Run a shell command, stream stdout to *on_log*, return (rc, stdout, stderr)."""
        import logging as _logging
        import os
        import subprocess
        import time as _time

        _logger = _logging.getLogger("pactown.builders")

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        _logger.debug("[builder] Running shell: %s (cwd=%s, timeout=%ds)", cmd, cwd, timeout)
        t0 = _time.monotonic()

        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(cwd),
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _logger.debug("[builder] Process started pid=%d", proc.pid)

        stdout_lines: list[str] = []

        try:
            if proc.stdout:
                for line in proc.stdout:
                    s = line.rstrip("\n")
                    stdout_lines.append(s)
                    if on_log:
                        try:
                            on_log(s)
                        except Exception:
                            pass

            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = _time.monotonic() - t0
            _logger.error("[builder] Command TIMED OUT after %.1fs (limit=%ds) – killing pid=%d: %s", elapsed, timeout, proc.pid, cmd)
            if on_log:
                try:
                    on_log(f"[builder] TIMEOUT after {elapsed:.0f}s – killing process")
                except Exception:
                    pass
            proc.kill()
            proc.wait(timeout=10)
            tail = "\n".join(stdout_lines[-10:]) if stdout_lines else "(no output)"
            _logger.error("[builder] Last output before timeout:\n%s", tail)
            return -9, "\n".join(stdout_lines), f"Timed out after {elapsed:.0f}s"

        elapsed = _time.monotonic() - t0
        if rc != 0:
            tail = "\n".join(stdout_lines[-15:]) if stdout_lines else "(no output)"
            _logger.warning("[builder] Command failed (exit=%d) in %.1fs: %s\nOutput tail:\n%s", rc, elapsed, cmd, tail)
        else:
            _logger.info("[builder] Command succeeded (exit=0) in %.1fs: %s", elapsed, cmd)

        return rc, "\n".join(stdout_lines), ""
