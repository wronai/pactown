"""Dependency venv cache for fast startup."""
import hashlib
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Optional

from ..nfo_config import logged
from .helpers import _beat_every_s, _heartbeat, _run_streamed
from .types import CachedVenv

@logged
class DependencyCache:
    """
    Caches virtual environments by dependency hash.
    
    Instead of creating a new venv for each service, reuses existing venvs
    that have the same dependencies installed.
    """
    
    def __init__(
        self,
        cache_root: Path,
        max_cache_size: int = 20,
        max_age_hours: int = 24,
    ):
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.max_cache_size = max_cache_size
        self.max_age_seconds = max_age_hours * 3600
        self._cache: Dict[str, CachedVenv] = {}
        self._lock = Lock()
        self._load_existing()
    
    def _load_existing(self):
        """Load existing cached venvs from disk."""
        for venv_dir in self.cache_root.iterdir():
            if venv_dir.is_dir() and (venv_dir / "bin" / "python").exists():
                deps_file = venv_dir / ".deps"
                if deps_file.exists():
                    deps = deps_file.read_text().strip().split("\n")
                    deps_hash = self._hash_deps(deps)
                    self._cache[deps_hash] = CachedVenv(
                        deps_hash=deps_hash,
                        path=venv_dir,
                        created_at=venv_dir.stat().st_ctime,
                        last_used=time.time(),
                        deps=deps,
                    )
    
    def _hash_deps(self, deps: List[str]) -> str:
        """Create hash of dependencies for cache key."""
        # Normalize and sort deps for consistent hashing
        normalized = sorted([d.strip().lower() for d in deps if d.strip()])
        deps_str = "\n".join(normalized)
        return hashlib.sha256(deps_str.encode()).hexdigest()[:16]
    
    def get_cached_venv(self, deps: List[str]) -> Optional[CachedVenv]:
        """Get a cached venv for the given dependencies."""
        deps_hash = self._hash_deps(deps)
        
        with self._lock:
            cached = self._cache.get(deps_hash)
            if cached and cached.is_valid():
                cached.last_used = time.time()
                return cached
            if cached:
                del self._cache[deps_hash]
                if cached.path.exists():
                    shutil.rmtree(cached.path)
        
        return None

    def invalidate(self, deps: List[str]) -> None:
        deps_hash = self._hash_deps(deps)
        cached: Optional[CachedVenv] = None
        with self._lock:
            cached = self._cache.pop(deps_hash, None)
        if cached and cached.path.exists():
            shutil.rmtree(cached.path)

    def save_existing_venv(
        self,
        deps: List[str],
        venv_path: Path,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Optional[CachedVenv]:
        deps_hash = self._hash_deps(deps)
        src = Path(venv_path)
        if not src.exists():
            return None

        dst = self.cache_root / f"venv_{deps_hash}"

        if on_progress:
            on_progress(f"Caching venv ({deps_hash})")

        if dst.exists():
            shutil.rmtree(dst)

        def _copytree_fast(src_path: Path, dst_path: Path) -> None:
            try:
                shutil.copytree(src_path, dst_path, copy_function=os.link)
            except Exception:
                if dst_path.exists():
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)

        stop = Event()
        thr = Thread(
            target=_heartbeat,
            kwargs={
                "stop": stop,
                "on_log": on_progress,
                "message": f"[deploy] Caching venv ({deps_hash})",
                "interval_s": float(_beat_every_s()),
            },
            daemon=True,
        )
        thr.start()
        _copytree_fast(src, dst)
        stop.set()
        (dst / ".deps").write_text("\n".join(deps))

        cached = CachedVenv(
            deps_hash=deps_hash,
            path=dst,
            created_at=time.time(),
            last_used=time.time(),
            deps=deps,
        )

        with self._lock:
            self._cache[deps_hash] = cached
            self._cleanup_old()

        if on_progress:
            on_progress(f"Venv cached: {deps_hash}")

        return cached
    
    def create_and_cache(
        self,
        deps: List[str],
        on_progress: Optional[Callable[[str], None]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> CachedVenv:
        """Create a new venv with deps and cache it."""
        deps_hash = self._hash_deps(deps)
        venv_path = self.cache_root / f"venv_{deps_hash}"
        
        if on_progress:
            on_progress(f"Creating cached venv for {len(deps)} deps...")
        
        # Create venv
        if venv_path.exists():
            shutil.rmtree(venv_path)

        stop = Event()
        thr = Thread(
            target=_heartbeat,
            kwargs={
                "stop": stop,
                "on_log": on_progress,
                "message": f"[deploy] Creating cached venv ({len(deps)} deps)",
                "interval_s": float(_beat_every_s()),
            },
            daemon=True,
        )
        thr.start()
        try:
            _run_streamed(
                ["python3", "-m", "venv", str(venv_path)],
                on_log=on_progress,
                env=os.environ.copy(),
            )
        finally:
            stop.set()
        
        # Install deps
        if deps:
            pip_path = venv_path / "bin" / "pip"
            stop = Event()
            thr = Thread(
                target=_heartbeat,
                kwargs={
                    "stop": stop,
                    "on_log": on_progress,
                    "message": f"[deploy] Installing cached deps via pip ({len(deps)} deps)",
                    "interval_s": float(_beat_every_s()),
                },
                daemon=True,
            )
            thr.start()
            try:
                install_env = os.environ.copy()
                if env:
                    install_env.update(env)
                _run_streamed(
                    [str(pip_path), "install", "--disable-pip-version-check", "--progress-bar", "off"] + deps,
                    on_log=on_progress,
                    env=install_env,
                )
            finally:
                stop.set()
        
        # Save deps list
        (venv_path / ".deps").write_text("\n".join(deps))
        
        cached = CachedVenv(
            deps_hash=deps_hash,
            path=venv_path,
            created_at=time.time(),
            last_used=time.time(),
            deps=deps,
        )
        
        with self._lock:
            self._cache[deps_hash] = cached
            self._cleanup_old()
        
        if on_progress:
            on_progress(f"Cached venv created: {deps_hash}")
        
        return cached
    
    def _cleanup_old(self):
        """Remove old cache entries."""
        now = time.time()
        to_remove = []
        
        for deps_hash, cached in self._cache.items():
            if now - cached.last_used > self.max_age_seconds:
                to_remove.append(deps_hash)
        
        # Also remove if over max size (LRU)
        if len(self._cache) > self.max_cache_size:
            sorted_by_use = sorted(
                self._cache.items(),
                key=lambda x: x[1].last_used
            )
            to_remove.extend([h for h, _ in sorted_by_use[:len(self._cache) - self.max_cache_size]])
        
        for deps_hash in set(to_remove):
            if deps_hash in self._cache:
                cached = self._cache[deps_hash]
                if cached.path.exists():
                    shutil.rmtree(cached.path)
                del self._cache[deps_hash]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "cached_venvs": len(self._cache),
                "max_size": self.max_cache_size,
                "entries": [
                    {
                        "hash": c.deps_hash,
                        "deps_count": len(c.deps),
                        "age_hours": (time.time() - c.created_at) / 3600,
                    }
                    for c in self._cache.values()
                ]
            }


