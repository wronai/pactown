"""Optimized async sandbox creation."""
import asyncio
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..markpact_blocks import parse_blocks
from ..nfo_config import logged
from .cache import DependencyCache
from .pool import SandboxPool
from .helpers import _run_streamed
from .types import FastStartResult

@logged
class FastServiceStarter:
    """
    Optimized service starter with caching and parallel execution.
    
    Provides millisecond startup times by:
    1. Caching dependency venvs
    2. Reusing sandboxes with same deps
    3. Async health checks (optional)
    4. Parallel file writing
    """
    
    def __init__(
        self,
        sandbox_root: Path,
        cache_root: Optional[Path] = None,
        enable_caching: bool = True,
        enable_pool: bool = True,
    ):
        self.sandbox_root = sandbox_root
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        
        self.cache_root = cache_root or (sandbox_root / ".cache")
        self.enable_caching = enable_caching
        self.enable_pool = enable_pool
        
        if enable_caching:
            self.dep_cache = DependencyCache(self.cache_root / "venvs")
        else:
            self.dep_cache = None
        
        if enable_pool:
            self.sandbox_pool = SandboxPool(
                self.cache_root / "pool",
                self.dep_cache,
            )
        else:
            self.sandbox_pool = None
        
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    async def fast_create_sandbox(
        self,
        service_name: str,
        content: str,
        on_log: Optional[Callable[[str], None]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> FastStartResult:
        """
        Create a sandbox as fast as possible.
        
        Uses caching and optimizations to minimize startup time.
        Returns in milliseconds for cached deps.
        """
        start_time = time.time()
        cache_hit = False
        
        def log(msg: str):
            if on_log:
                on_log(msg)

        def verify_cached_venv(*, venv_path: Path) -> bool:
            py = venv_path / "bin" / "python"
            if not py.exists():
                return False

            deps_l = {d.strip().lower() for d in deps if d.strip()}
            rc = (run_cmd or "").strip().lower()

            imports: list[str] = []
            if rc.startswith("uvicorn ") or " uvicorn " in f" {rc} ":
                imports.extend(["uvicorn", "click"])
            elif rc.startswith("gunicorn ") or " gunicorn " in f" {rc} ":
                imports.append("gunicorn")

            if "fastapi" in deps_l and "fastapi" not in imports:
                imports.append("fastapi")
            if "flask" in deps_l and "flask" not in imports:
                imports.append("flask")

            if not imports:
                return True

            code = "import importlib\n" + "\n".join([f"importlib.import_module({m!r})" for m in imports])
            check_env = os.environ.copy()
            if env:
                check_env.update({str(k): str(v) for k, v in env.items() if k is not None and v is not None})

            try:
                res = subprocess.run(
                    [str(py), "-c", code],
                    capture_output=True,
                    text=True,
                    env=check_env,
                    timeout=20,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return False

            if res.returncode != 0:
                out = ((res.stderr or "") + "\n" + (res.stdout or "")).strip()[:2000]
                if out:
                    log(f"Cached venv verification failed: {out}")
                return False

            return True
        
        # Parse content
        try:
            blocks = parse_blocks(content)
        except Exception as e:
            return FastStartResult(
                success=False,
                startup_time_ms=(time.time() - start_time) * 1000,
                cache_hit=False,
                message=f"Parse error: {e}",
            )
        
        # Extract deps and files
        deps: List[str] = []
        files: Dict[str, str] = {}
        run_cmd: Optional[str] = None
        
        for block in blocks:
            if block.kind == "deps":
                deps.extend([d.strip() for d in block.body.strip().split("\n") if d.strip()])
            elif block.kind == "file":
                file_path = block.get_path() or "main.py"
                files[file_path] = block.body
            elif block.kind == "run":
                run_cmd = block.body.strip()
        
        # Create sandbox directory
        sandbox_path = self.sandbox_root / service_name
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)
        sandbox_path.mkdir(parents=True)
        
        # Write files in parallel
        write_start = time.time()
        await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._write_files_parallel,
            sandbox_path,
            files,
        )
        log(f"⚡ Files written in {(time.time() - write_start) * 1000:.0f}ms")
        
        # Handle dependencies with caching
        venv_path = None
        if deps and self.enable_caching and self.dep_cache:
            cached = self.dep_cache.get_cached_venv(deps)

            if cached:
                ok = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    lambda: verify_cached_venv(venv_path=cached.path),
                )
                if not ok:
                    log("⚠️ Cached venv appears corrupted - rebuilding")
                    try:
                        self.dep_cache.invalidate(deps)
                    except Exception:
                        pass
                    cached = None

            if cached:
                cache_hit = True
                venv_path = cached.path
                log(f"⚡ Cache hit! Reusing venv ({cached.deps_hash})")

                # Symlink to cached venv instead of copying
                venv_link = sandbox_path / ".venv"
                venv_link.symlink_to(cached.path)
            else:
                # Create and cache new venv
                log(f"📦 Cache miss, installing {len(deps)} deps...")
                cached = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    self.dep_cache.create_and_cache,
                    deps,
                    log,
                    env,
                )
                venv_path = cached.path
                venv_link = sandbox_path / ".venv"
                venv_link.symlink_to(cached.path)
        elif deps:
            # No caching, install directly
            log(f"📦 Installing {len(deps)} deps (no cache)...")
            await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._install_deps_direct,
                sandbox_path,
                deps,
                env,
            )
            venv_path = sandbox_path / ".venv"
        
        # Write requirements.txt
        if deps:
            (sandbox_path / "requirements.txt").write_text("\n".join(deps))
        
        total_time_ms = (time.time() - start_time) * 1000
        
        return FastStartResult(
            success=True,
            startup_time_ms=total_time_ms,
            cache_hit=cache_hit,
            message=f"Sandbox ready in {total_time_ms:.0f}ms" + (" (cached)" if cache_hit else ""),
            sandbox_path=sandbox_path,
        )
    
    def _write_files_parallel(self, sandbox_path: Path, files: Dict[str, str]):
        """Write multiple files in parallel."""
        def write_file(item):
            path, content = item
            file_path = sandbox_path / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(write_file, files.items()))
    
    def _install_deps_direct(self, sandbox_path: Path, deps: List[str], env: Optional[Dict[str, str]] = None):
        """Install deps directly without caching."""
        venv_path = sandbox_path / ".venv"
        _run_streamed(["python3", "-m", "venv", str(venv_path)], on_log=None, env=os.environ.copy())
        pip_path = venv_path / "bin" / "pip"
        install_env = os.environ.copy()
        if env:
            install_env.update(env)
        _run_streamed(
            [str(pip_path), "install", "--disable-pip-version-check", "--progress-bar", "off"] + deps,
            on_log=None,
            env=install_env,
        )
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get caching statistics."""
        stats = {
            "caching_enabled": self.enable_caching,
            "pool_enabled": self.enable_pool,
        }
        if self.dep_cache:
            stats["dep_cache"] = self.dep_cache.get_stats()
        return stats


