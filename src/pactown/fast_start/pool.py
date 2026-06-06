"""Pre-warmed sandbox pool."""
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, List, Optional

from ..nfo_config import logged
from .cache import DependencyCache
from .types import PrewarmedSandbox

@logged
class SandboxPool:
    """
    Pool of pre-warmed sandboxes for instant startup.
    
    Keeps a pool of ready-to-use sandboxes with common dependency sets
    pre-installed. When a service needs to start, it can grab a pre-warmed
    sandbox instead of creating one from scratch.
    """
    
    COMMON_STACKS = [
        # Python web
        ["fastapi", "uvicorn"],  # Basic FastAPI
        ["fastapi", "uvicorn", "pydantic"],  # FastAPI with Pydantic
        ["fastapi", "uvicorn", "sqlalchemy"],  # FastAPI with DB
        ["flask", "gunicorn"],  # Flask
        # Python desktop
        ["pyinstaller"],  # PyInstaller standalone
        ["PyQt6", "pyinstaller"],  # PyQt desktop
        ["kivy", "buildozer"],  # Kivy mobile
    ]
    
    def __init__(
        self,
        pool_root: Path,
        dep_cache: DependencyCache,
        pool_size_per_stack: int = 2,
    ):
        self.pool_root = pool_root
        self.pool_root.mkdir(parents=True, exist_ok=True)
        self.dep_cache = dep_cache
        self.pool_size = pool_size_per_stack
        self._pool: Dict[str, List[PrewarmedSandbox]] = {}
        self._lock = Lock()
    
    def _hash_deps(self, deps: List[str]) -> str:
        """Hash deps for pool key."""
        return self.dep_cache._hash_deps(deps)
    
    def warm_pool(self, on_progress: Optional[Callable[[str], None]] = None):
        """Pre-warm the sandbox pool with common stacks."""
        for stack in self.COMMON_STACKS:
            deps_hash = self._hash_deps(stack)
            
            # Ensure we have a cached venv
            if not self.dep_cache.get_cached_venv(stack):
                if on_progress:
                    on_progress(f"Warming cache for: {', '.join(stack)}")
                self.dep_cache.create_and_cache(stack, on_progress)
    
    def get_prewarmed(self, deps: List[str]) -> Optional[PrewarmedSandbox]:
        """Get a pre-warmed sandbox for the given deps if available."""
        deps_hash = self._hash_deps(deps)
        
        with self._lock:
            if deps_hash in self._pool:
                for sandbox in self._pool[deps_hash]:
                    if not sandbox.in_use:
                        sandbox.in_use = True
                        return sandbox
        
        return None
    
    def release(self, sandbox: PrewarmedSandbox):
        """Release a sandbox back to the pool."""
        with self._lock:
            sandbox.in_use = False


