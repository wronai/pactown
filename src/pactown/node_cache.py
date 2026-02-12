"""Node modules cache – avoid re-downloading npm packages across builds.

Works analogously to ``fast_start.DependencyCache`` for Python venvs:
- Hashes ``package.json`` (name + dependencies + devDependencies) to produce
  a cache key.
- Stores a hardlink-copy of ``node_modules`` under ``<cache_root>/<hash>/``.
- On cache hit, restores ``node_modules`` via hardlinks (instant on same FS).
- LRU eviction when the cache exceeds ``max_entries``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from .nfo_config import logged
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CachedNodeModules:
    """A cached ``node_modules`` directory keyed by dependency hash."""

    deps_hash: str
    path: Path  # <cache_root>/<hash>/node_modules
    created_at: float
    last_used: float
    pkg_snapshot: str  # original package.json content used to create this entry

    def is_valid(self) -> bool:
        """Return *True* if the cached ``node_modules`` directory still exists."""
        return self.path.is_dir() and any(self.path.iterdir())


@logged
class NodeModulesCache:
    """Cache ``node_modules`` directories by ``package.json`` content hash.

    The cache key is computed from the *name*, *dependencies*, and
    *devDependencies* fields of ``package.json`` so that cosmetic changes
    (description, scripts) do **not** invalidate the cache.

    Typical savings: **10-15 s** per Electron/Capacitor/Tauri build after
    the first cold install.
    """

    def __init__(
        self,
        cache_root: Path,
        max_entries: int = 20,
        max_age_hours: int = 72,
    ) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self.max_age_seconds = max_age_hours * 3600
        self._cache: Dict[str, CachedNodeModules] = {}
        self._lock = Lock()
        self._load_existing()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, pkg_json_content: str) -> Optional[CachedNodeModules]:
        """Look up a cached ``node_modules`` for the given ``package.json``."""
        h = self._hash_pkg(pkg_json_content)
        with self._lock:
            entry = self._cache.get(h)
            if entry and entry.is_valid():
                entry.last_used = time.time()
                return entry
            if entry:
                # Stale / broken – remove it
                del self._cache[h]
                shutil.rmtree(entry.path.parent, ignore_errors=True)
        return None

    def restore(
        self,
        pkg_json_content: str,
        dest: Path,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Restore cached ``node_modules`` into *dest* (the sandbox directory).

        Returns *True* on cache hit, *False* on miss.
        """
        entry = self.get(pkg_json_content)
        if entry is None:
            return False

        nm_dst = dest / "node_modules"
        if nm_dst.exists():
            shutil.rmtree(nm_dst)

        if on_log:
            on_log(f"⚡ Restoring cached node_modules ({entry.deps_hash})")

        _copytree_hardlink(entry.path, nm_dst)
        return True

    def save(
        self,
        pkg_json_content: str,
        sandbox_path: Path,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> Optional[CachedNodeModules]:
        """Save *sandbox_path/node_modules* into the cache."""
        nm_src = sandbox_path / "node_modules"
        if not nm_src.is_dir():
            return None

        h = self._hash_pkg(pkg_json_content)
        cache_dir = self.cache_root / h
        nm_dst = cache_dir / "node_modules"

        if nm_dst.exists():
            shutil.rmtree(nm_dst)
        cache_dir.mkdir(parents=True, exist_ok=True)

        if on_log:
            on_log(f"💾 Caching node_modules ({h})")

        _copytree_hardlink(nm_src, nm_dst)

        # Persist the package.json snapshot so we can verify on load
        (cache_dir / "package.json").write_text(pkg_json_content)

        entry = CachedNodeModules(
            deps_hash=h,
            path=nm_dst,
            created_at=time.time(),
            last_used=time.time(),
            pkg_snapshot=pkg_json_content,
        )

        with self._lock:
            self._cache[h] = entry
            self._evict()

        if on_log:
            on_log(f"✅ node_modules cached ({h})")
        return entry

    def invalidate(self, pkg_json_content: str) -> None:
        """Remove cache entry for the given ``package.json``."""
        h = self._hash_pkg(pkg_json_content)
        with self._lock:
            entry = self._cache.pop(h, None)
        if entry:
            shutil.rmtree(entry.path.parent, ignore_errors=True)

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic cache statistics."""
        with self._lock:
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "items": [
                    {
                        "hash": e.deps_hash,
                        "age_hours": round((time.time() - e.created_at) / 3600, 1),
                        "valid": e.is_valid(),
                    }
                    for e in self._cache.values()
                ],
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_pkg(pkg_json_content: str) -> str:
        """Compute a stable cache key from ``package.json`` content.

        Only *name*, *dependencies*, and *devDependencies* are hashed so
        that unrelated changes (description, scripts, build config) do not
        bust the cache.
        """
        try:
            data = json.loads(pkg_json_content)
        except Exception:
            data = {}
        key_parts = {
            "name": data.get("name", ""),
            "dependencies": _sorted_deps(data.get("dependencies")),
            "devDependencies": _sorted_deps(data.get("devDependencies")),
        }
        raw = json.dumps(key_parts, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_existing(self) -> None:
        """Scan cache_root for previously cached entries."""
        if not self.cache_root.is_dir():
            return
        for entry_dir in self.cache_root.iterdir():
            if not entry_dir.is_dir():
                continue
            nm = entry_dir / "node_modules"
            pkg = entry_dir / "package.json"
            if nm.is_dir() and pkg.is_file():
                try:
                    content = pkg.read_text()
                    h = self._hash_pkg(content)
                    self._cache[h] = CachedNodeModules(
                        deps_hash=h,
                        path=nm,
                        created_at=entry_dir.stat().st_ctime,
                        last_used=time.time(),
                        pkg_snapshot=content,
                    )
                except Exception:
                    pass

    def _evict(self) -> None:
        """Remove expired or excess entries (LRU)."""
        now = time.time()
        expired = [h for h, e in self._cache.items() if now - e.last_used > self.max_age_seconds]
        for h in expired:
            e = self._cache.pop(h, None)
            if e:
                shutil.rmtree(e.path.parent, ignore_errors=True)

        if len(self._cache) > self.max_entries:
            by_lru = sorted(self._cache.items(), key=lambda kv: kv[1].last_used)
            excess = len(self._cache) - self.max_entries
            for h, e in by_lru[:excess]:
                self._cache.pop(h, None)
                shutil.rmtree(e.path.parent, ignore_errors=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sorted_deps(deps: Any) -> dict:
    """Return a sorted copy of a deps dict, or empty dict."""
    if not isinstance(deps, dict):
        return {}
    return dict(sorted(deps.items()))


def _copytree_hardlink(src: Path, dst: Path) -> None:
    """Copy a directory tree using hardlinks where possible (same FS = instant)."""
    try:
        shutil.copytree(src, dst, copy_function=os.link)
    except Exception:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
