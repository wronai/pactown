"""
Fast startup module for pactown.

Provides optimizations for rapid service startup:
- Dependency caching (reuse venvs with same deps)
- Pre-warmed sandbox pool
- Parallel service startup
- Async health checks
- Hot reload without reinstall
"""

import asyncio
import hashlib
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Event, Thread
from typing import Any, Callable, Dict, List, Optional, Set

from .markpact_blocks import parse_blocks


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


def _heartbeat(
    *,
    stop: Event,
    on_log: Optional[Callable[[str], None]],
    message: str,
    interval_s: float = 1.0,
) -> None:
    if not on_log:
        return
    started = time.monotonic()
    while not stop.wait(interval_s):
        elapsed = int(time.monotonic() - started)
        on_log(f"⏳ {message} (elapsed={elapsed}s)")


def _beat_every_s(*, default: int = 5) -> int:
    try:
        return max(1, int(os.environ.get("PACTOWN_HEALTH_HEARTBEAT_S", str(default))))
    except Exception:
        return default


def _run_streamed(
    cmd: List[str],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> None:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
    )
    try:
        if proc.stdout:
            for line in proc.stdout:
                s = (line or "").rstrip("\n")
                if not s:
                    continue
                if on_log:
                    on_log(s)
        rc = proc.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass


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


class SandboxPool:
    """
    Pool of pre-warmed sandboxes for instant startup.
    
    Keeps a pool of ready-to-use sandboxes with common dependency sets
    pre-installed. When a service needs to start, it can grab a pre-warmed
    sandbox instead of creating one from scratch.
    """
    
    COMMON_STACKS = [
        ["fastapi", "uvicorn"],  # Basic FastAPI
        ["fastapi", "uvicorn", "pydantic"],  # FastAPI with Pydantic
        ["fastapi", "uvicorn", "sqlalchemy"],  # FastAPI with DB
        ["flask", "gunicorn"],  # Flask
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


class ParallelServiceRunner:
    """
    Run multiple services in parallel with optimized startup.
    """
    
    def __init__(self, fast_starter: FastServiceStarter, max_parallel: int = 4):
        self.fast_starter = fast_starter
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
    
    async def run_parallel(
        self,
        services: List[Dict[str, Any]],
        on_service_log: Optional[Callable[[str, str], None]] = None,
    ) -> List[FastStartResult]:
        """
        Run multiple services in parallel.
        
        Args:
            services: List of dicts with {service_id, content, port}
            on_service_log: Callback (service_id, message)
        
        Returns:
            List of FastStartResult for each service
        """
        async def run_one(svc: Dict[str, Any]) -> FastStartResult:
            async with self._semaphore:
                service_id = svc["service_id"]
                
                def log(msg: str):
                    if on_service_log:
                        on_service_log(service_id, msg)
                
                return await self.fast_starter.fast_create_sandbox(
                    service_name=f"service_{service_id}",
                    content=svc["content"],
                    on_log=log,
                )
        
        results = await asyncio.gather(*[run_one(s) for s in services])
        return list(results)


# Global fast starter instance
_fast_starter: Optional[FastServiceStarter] = None


def get_fast_starter(sandbox_root: Optional[Path] = None) -> FastServiceStarter:
    """Get or create the global fast starter instance."""
    global _fast_starter
    if _fast_starter is None:
        import tempfile
        root = sandbox_root or Path(os.environ.get("PACTOWN_SANDBOX_ROOT", tempfile.gettempdir() + "/pactown-sandboxes"))
        _fast_starter = FastServiceStarter(root)
    return _fast_starter
