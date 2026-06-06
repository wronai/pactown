from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .validate import load_sandbox_manifest


@dataclass
class PhaseTracker:
    """Track sandbox lifecycle phases declared in pactown.sandbox.yaml."""

    phases: list[str] = field(default_factory=list)
    current: Optional[str] = None
    completed: list[str] = field(default_factory=list)
    on_log: Optional[Callable[[str], None]] = None

    @classmethod
    def from_manifest(cls, manifest: Optional[dict[str, Any]], *, on_log: Optional[Callable[[str], None]] = None) -> PhaseTracker:
        names: list[str] = []
        if isinstance(manifest, dict):
            body = manifest.get("spec") or {}
            validation = body.get("validation") or {}
            for phase in validation.get("phases") or []:
                if isinstance(phase, dict):
                    name = str(phase.get("name") or "").strip()
                    if name:
                        names.append(name)
        if not names:
            names = ["manifest", "scaffold", "deps", "run", "health"]
        return cls(phases=names, on_log=on_log)

    @classmethod
    def from_sandbox(cls, sandbox_path: Optional[Path], *, on_log: Optional[Callable[[str], None]] = None) -> PhaseTracker:
        if sandbox_path is None:
            return cls(on_log=on_log)
        manifest_path = sandbox_path / "pactown.sandbox.yaml"
        if not manifest_path.exists():
            return cls(on_log=on_log)
        try:
            return cls.from_manifest(load_sandbox_manifest(manifest_path), on_log=on_log)
        except Exception:
            return cls(on_log=on_log)

    def enter(self, phase: str) -> None:
        self.current = phase
        if self.on_log:
            self.on_log(f"[iac:{phase}] starting")

    def complete(self, phase: str) -> None:
        if phase not in self.completed:
            self.completed.append(phase)
        if self.on_log:
            self.on_log(f"[iac:{phase}] ok")
        self.current = None

    def fail(self, phase: str, message: str = "") -> None:
        if self.on_log:
            detail = f": {message}" if message else ""
            self.on_log(f"[iac:{phase}] failed{detail}")
        self.current = phase

    def summary(self) -> dict[str, Any]:
        return {
            "phases": list(self.phases),
            "completed": list(self.completed),
            "current": self.current,
        }
