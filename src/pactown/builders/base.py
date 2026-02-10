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
        import os
        import subprocess

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

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

        stdout_lines: list[str] = []

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
        return rc, "\n".join(stdout_lines), ""
