"""Tests for NodeModulesCache – node_modules caching via hardlink-copy."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import pytest

from pactown.node_cache import NodeModulesCache, CachedNodeModules, _sorted_deps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pkg_json(name: str = "app", deps: Optional[dict] = None, dev_deps: Optional[dict] = None) -> str:
    """Return a package.json string."""
    return json.dumps({
        "name": name,
        "version": "1.0.0",
        "dependencies": deps or {},
        "devDependencies": dev_deps or {},
    }, indent=2)


def _populate_node_modules(sandbox: Path, modules: list[str] | None = None) -> Path:
    """Create a fake node_modules directory with some modules."""
    nm = sandbox / "node_modules"
    nm.mkdir(parents=True, exist_ok=True)
    for mod in (modules or ["electron", "electron-builder"]):
        mod_dir = nm / mod
        mod_dir.mkdir(parents=True, exist_ok=True)
        (mod_dir / "index.js").write_text(f"// {mod}")
        (mod_dir / "package.json").write_text(json.dumps({"name": mod, "version": "1.0.0"}))
    return nm


# ===========================================================================
# Hash stability
# ===========================================================================

class TestHashStability:
    def test_same_deps_same_hash(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = _make_pkg_json("app", {"a": "1"}, {"b": "2"})
        pkg2 = _make_pkg_json("app", {"a": "1"}, {"b": "2"})
        assert cache._hash_pkg(pkg1) == cache._hash_pkg(pkg2)

    def test_different_deps_different_hash(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = _make_pkg_json("app", {"a": "1"})
        pkg2 = _make_pkg_json("app", {"a": "2"})
        assert cache._hash_pkg(pkg1) != cache._hash_pkg(pkg2)

    def test_order_independent(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = json.dumps({"name": "x", "dependencies": {"b": "1", "a": "2"}})
        pkg2 = json.dumps({"name": "x", "dependencies": {"a": "2", "b": "1"}})
        assert cache._hash_pkg(pkg1) == cache._hash_pkg(pkg2)

    def test_description_change_does_not_bust_cache(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = json.dumps({"name": "x", "description": "old", "dependencies": {"a": "1"}})
        pkg2 = json.dumps({"name": "x", "description": "new", "dependencies": {"a": "1"}})
        assert cache._hash_pkg(pkg1) == cache._hash_pkg(pkg2)

    def test_scripts_change_does_not_bust_cache(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = json.dumps({"name": "x", "scripts": {"build": "v1"}, "dependencies": {"a": "1"}})
        pkg2 = json.dumps({"name": "x", "scripts": {"build": "v2"}, "dependencies": {"a": "1"}})
        assert cache._hash_pkg(pkg1) == cache._hash_pkg(pkg2)

    def test_name_change_busts_cache(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        pkg1 = _make_pkg_json("app-a", {"a": "1"})
        pkg2 = _make_pkg_json("app-b", {"a": "1"})
        assert cache._hash_pkg(pkg1) != cache._hash_pkg(pkg2)

    def test_invalid_json_returns_stable_hash(self) -> None:
        cache = NodeModulesCache.__new__(NodeModulesCache)
        h1 = cache._hash_pkg("not json")
        h2 = cache._hash_pkg("{broken")
        assert h1 == h2  # both degrade to empty dict
        assert len(h1) == 16


# ===========================================================================
# Save + restore round-trip
# ===========================================================================

class TestSaveRestore:
    def test_save_and_restore(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)

        # Save
        entry = cache.save(pkg, sandbox)
        assert entry is not None
        assert entry.is_valid()

        # Wipe sandbox node_modules
        import shutil
        shutil.rmtree(sandbox / "node_modules")
        assert not (sandbox / "node_modules").exists()

        # Restore
        hit = cache.restore(pkg, sandbox)
        assert hit
        assert (sandbox / "node_modules").is_dir()
        assert (sandbox / "node_modules" / "electron" / "index.js").exists()
        assert (sandbox / "node_modules" / "electron-builder" / "index.js").exists()

    def test_cache_miss_returns_false(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("unknown-app")
        hit = cache.restore(pkg, sandbox)
        assert not hit

    def test_save_without_node_modules_returns_none(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp")
        entry = cache.save(pkg, sandbox)
        assert entry is None

    def test_restore_overwrites_existing_node_modules(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox, ["electron", "electron-builder"])

        cache.save(pkg, sandbox)

        # Create a different node_modules in sandbox
        import shutil
        shutil.rmtree(sandbox / "node_modules")
        _populate_node_modules(sandbox, ["express"])
        assert (sandbox / "node_modules" / "express").exists()

        # Restore should replace with cached version
        cache.restore(pkg, sandbox)
        assert (sandbox / "node_modules" / "electron").exists()
        assert not (sandbox / "node_modules" / "express").exists()


# ===========================================================================
# Persistence across instances
# ===========================================================================

class TestPersistence:
    def test_new_instance_loads_existing_cache(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "cache"
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)

        # Save with first instance
        cache1 = NodeModulesCache(cache_root)
        cache1.save(pkg, sandbox)

        # Create new instance – should load from disk
        cache2 = NodeModulesCache(cache_root)
        entry = cache2.get(pkg)
        assert entry is not None
        assert entry.is_valid()


# ===========================================================================
# Invalidation
# ===========================================================================

class TestInvalidation:
    def test_invalidate_removes_entry(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)

        cache.save(pkg, sandbox)
        assert cache.get(pkg) is not None

        cache.invalidate(pkg)
        assert cache.get(pkg) is None

    def test_invalidate_nonexistent_is_noop(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        cache.invalidate(_make_pkg_json("nothing"))  # should not raise


# ===========================================================================
# Eviction (LRU)
# ===========================================================================

class TestEviction:
    def test_max_entries_evicts_lru(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache", max_entries=2)

        entries = []
        for i in range(3):
            sandbox = tmp_path / f"sandbox_{i}"
            sandbox.mkdir()
            pkg = _make_pkg_json(f"app-{i}", dev_deps={"dep": f"{i}.0.0"})
            (sandbox / "package.json").write_text(pkg)
            _populate_node_modules(sandbox, [f"mod-{i}"])
            entry = cache.save(pkg, sandbox)
            entries.append((pkg, entry))
            time.sleep(0.01)  # ensure different last_used times

        # First entry should have been evicted (LRU)
        assert cache.get(entries[0][0]) is None
        # Last two should still be there
        assert cache.get(entries[1][0]) is not None
        assert cache.get(entries[2][0]) is not None


# ===========================================================================
# Stats
# ===========================================================================

class TestStats:
    def test_get_stats_empty(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        stats = cache.get_stats()
        assert stats["entries"] == 0
        assert stats["max_entries"] == 20
        assert stats["items"] == []

    def test_get_stats_with_entries(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)
        cache.save(pkg, sandbox)

        stats = cache.get_stats()
        assert stats["entries"] == 1
        assert len(stats["items"]) == 1
        assert stats["items"][0]["valid"] is True


# ===========================================================================
# on_log callback
# ===========================================================================

class TestOnLog:
    def test_save_sends_log(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)

        logs: list[str] = []
        cache.save(pkg, sandbox, on_log=logs.append)
        assert any("cach" in l.lower() for l in logs)

    def test_restore_sends_log(self, tmp_path: Path) -> None:
        cache = NodeModulesCache(tmp_path / "cache")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        pkg = _make_pkg_json("myapp", dev_deps={"electron": "^33.0.0"})
        (sandbox / "package.json").write_text(pkg)
        _populate_node_modules(sandbox)
        cache.save(pkg, sandbox)

        logs: list[str] = []
        cache.restore(pkg, sandbox, on_log=logs.append)
        assert any("restor" in l.lower() for l in logs)


# ===========================================================================
# _sorted_deps helper
# ===========================================================================

class TestSortedDeps:
    def test_sorts_dict(self) -> None:
        assert _sorted_deps({"b": "2", "a": "1"}) == {"a": "1", "b": "2"}

    def test_non_dict_returns_empty(self) -> None:
        assert _sorted_deps(None) == {}
        assert _sorted_deps("not a dict") == {}
        assert _sorted_deps([1, 2]) == {}

    def test_empty_dict(self) -> None:
        assert _sorted_deps({}) == {}
