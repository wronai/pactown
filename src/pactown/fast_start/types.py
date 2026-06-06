"""Fast-start dataclasses."""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

@dataclass
class CachedVenv:
    """Cached virtual environment for a specific dependency set."""
    deps_hash: str
    path: Path
    created_at: float
    last_used: float
    deps: List[str]
    
    def is_valid(self) -> bool:
        """Check if venv still exists and is valid."""
        return (self.path / "bin" / "python").exists()


@dataclass
class PrewarmedSandbox:
    """Pre-created sandbox ready for immediate use."""
    path: Path
    venv_path: Optional[Path]
    deps_hash: str
    created_at: float
    in_use: bool = False


@dataclass
class FastStartResult:
    """Result of fast startup."""
    success: bool
    startup_time_ms: float
    cache_hit: bool
    message: str
    sandbox_path: Optional[Path] = None

