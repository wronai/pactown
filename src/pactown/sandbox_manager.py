"""Sandbox manager for pactown services."""

import json
import logging
import os
import inspect
import re
import shutil
import stat
import signal
import subprocess
import tempfile
import time
import socket
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from threading import Event
from threading import Thread
from threading import Lock
from typing import Callable, Optional, List, Dict, Any

from markpact import Sandbox, ensure_venv

from .config import ServiceConfig
from .markpact_blocks import parse_blocks
from .fast_start import DependencyCache

# Configure detailed logging
logger = logging.getLogger("pactown.sandbox")
logger.setLevel(logging.DEBUG)


def _ui_log_level() -> int:
    raw = str(os.environ.get("PACTOWN_UI_LOG_LEVEL", "INFO") or "INFO").strip().upper()
    if raw == "DEBUG":
        return logging.DEBUG
    if raw == "WARNING" or raw == "WARN":
        return logging.WARNING
    if raw == "ERROR":
        return logging.ERROR
    if raw == "CRITICAL":
        return logging.CRITICAL
    return logging.INFO


def _should_emit_to_ui(level: str) -> bool:
    try:
        lvl = int(getattr(logging, str(level).upper()))
    except Exception:
        lvl = logging.INFO
    return lvl >= _ui_log_level()


_ON_LOG_ACCEPTS_LEVEL: dict[int, bool] = {}


def _call_on_log(on_log: Optional[Callable[..., None]], msg: str, level: str) -> None:
    if not on_log:
        return
    key = id(on_log)
    accepts = _ON_LOG_ACCEPTS_LEVEL.get(key)
    if accepts is None:
        try:
            sig = inspect.signature(on_log)
            params = list(sig.parameters.values())
            accepts = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) or len(params) >= 2
        except Exception:
            accepts = False
        _ON_LOG_ACCEPTS_LEVEL[key] = accepts
    if accepts:
        on_log(msg, level)
    else:
        on_log(msg)


def _heartbeat(
    *,
    stop: Event,
    on_log: Optional[Callable[..., None]],
    message: str,
    interval_s: float = 1.0,
) -> None:
    if not on_log:
        return
    started = time.monotonic()
    ticks = 0
    while not stop.wait(interval_s):
        ticks += 1
        elapsed = int(time.monotonic() - started)
        if _should_emit_to_ui("INFO"):
            _call_on_log(on_log, f"⏳ {message} (elapsed={elapsed}s)", "INFO")


def _beat_every_s(*, default: int = 5) -> int:
    try:
        return max(1, int(os.environ.get("PACTOWN_HEALTH_HEARTBEAT_S", str(default))))
    except Exception:
        return default

# File handler for persistent logs
LOG_DIR = Path(os.environ.get("PACTOWN_LOG_DIR", tempfile.gettempdir() + "/pactown-logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log_path = str(LOG_DIR / "sandbox.log")
if not any(
    isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == _log_path
    for h in logger.handlers
):
    file_handler = logging.FileHandler(_log_path)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))
    logger.addHandler(file_handler)


def _path_debug(path: Path) -> str:
    try:
        st = path.stat() if path.exists() else None
        mode = oct(st.st_mode & 0o777) if st else "-"
        uid = st.st_uid if st else "-"
        gid = st.st_gid if st else "-"
    except Exception:
        mode, uid, gid = "?", "?", "?"
    try:
        readable = os.access(path, os.R_OK)
        writable = os.access(path, os.W_OK)
        executable = os.access(path, os.X_OK)
    except Exception:
        readable, writable, executable = False, False, False
    return (
        f"path={path} exists={path.exists()} is_dir={path.is_dir()} is_file={path.is_file()} "
        f"mode={mode} uid={uid} gid={gid} access=r{int(readable)}w{int(writable)}x{int(executable)}"
    )


def _escape_dotenv_value(value: str) -> str:
    v = str(value)
    v = v.replace("\\", "\\\\")
    v = v.replace("\n", "\\n")
    v = v.replace("\r", "\\r")
    v = v.replace('"', '\\"')
    return f'"{v}"'


def _write_dotenv_file(sandbox_path: Path, env: dict[str, str]) -> None:
    lines: list[str] = []
    for key, value in (env or {}).items():
        if value is None:
            continue
        if not isinstance(key, str):
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        lines.append(f"{key}={_escape_dotenv_value(str(value))}")

    dotenv_path = sandbox_path / ".env"
    dotenv_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    try:
        dotenv_path.chmod(0o600)
    except Exception:
        pass


def _sandbox_fallback_ids() -> tuple[int, int]:
    try:
        uid = int(os.environ.get("PACTOWN_SANDBOX_UID", "65534"))
    except Exception:
        uid = 65534
    try:
        gid = int(os.environ.get("PACTOWN_SANDBOX_GID", str(uid)))
    except Exception:
        gid = uid
    return uid, gid


def _chown_sandbox_tree(sandbox_path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(sandbox_path, uid, gid)
    except Exception:
        pass
    try:
        sandbox_path.chmod(0o700)
    except Exception:
        pass

    for root, dirnames, filenames in os.walk(sandbox_path):
        if ".venv" in dirnames:
            dirnames.remove(".venv")

        root_path = Path(root)
        try:
            os.chown(root_path, uid, gid)
        except Exception:
            pass
        try:
            root_path.chmod(0o700)
        except Exception:
            pass

        for name in filenames:
            p = root_path / name
            try:
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    continue
            except Exception:
                continue
            try:
                os.chown(p, uid, gid)
            except Exception:
                pass


@dataclass
class ServiceProcess:
    """Represents a running service process."""
    name: str
    pid: int
    port: Optional[int]
    sandbox_path: Path
    process: Optional[subprocess.Popen] = None
    started_at: float = field(default_factory=time.time)

    @property
    def is_running(self) -> bool:
        if self.process:
            return self.process.poll() is None
        try:
            os.kill(self.pid, 0)
            if self.port:
                try:
                    with socket.create_connection(("127.0.0.1", int(self.port)), timeout=0.2):
                        return True
                except OSError:
                    return False
            return True
        except OSError:
            return False


class SandboxManager:
    """Manages sandboxes for multiple services."""

    @staticmethod
    def _is_node_lang(lang: str) -> bool:
        l = (lang or "").strip().lower()
        return l in {"node", "js", "javascript", "npm"}

    @staticmethod
    def _infer_node_project(*, blocks: list, deps: list[str], run_cmd: str) -> bool:
        for b in blocks:
            if getattr(b, "kind", "") == "deps" and SandboxManager._is_node_lang(getattr(b, "lang", "")):
                return True
            if getattr(b, "kind", "") == "file":
                try:
                    p = str(b.get_path() or "").strip()
                except Exception:
                    p = ""
                if p:
                    pl = p.lower()
                    if pl == "package.json" or pl.endswith((".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")):
                        return True
        rc = (run_cmd or "").strip().lower()
        if rc.startswith("node ") or rc.startswith("npm ") or rc.startswith("pnpm ") or rc.startswith("yarn "):
            return True
        if " node " in f" {rc} ":
            return True
        deps_l = {d.strip().lower() for d in (deps or []) if str(d).strip()}
        if "express" in deps_l and ("node" in rc or "npm" in rc):
            return True
        return False

    @staticmethod
    def _ensure_package_json(*, sandbox_path: Path, service_name: str, deps: list[str]) -> None:
        pkg_path = sandbox_path / "package.json"
        if pkg_path.exists():
            return

        deps_obj: dict[str, str] = {}
        for dep in deps:
            d = str(dep).strip()
            if not d:
                continue
            if d.startswith("#"):
                continue
            if " " in d:
                d = d.split()[0]
            if "@" in d and not d.startswith("@"):  # e.g. express@4
                name, version = d.rsplit("@", 1)
                name = name.strip()
                version = version.strip()
                if name:
                    deps_obj[name] = version or "latest"
            else:
                deps_obj[d] = "latest"

        pkg_path.write_text(
            json.dumps(
                {
                    "name": re.sub(r"[^a-z0-9-_]", "-", str(service_name).lower()) or "pactown-app",
                    "version": "1.0.0",
                    "private": True,
                    "dependencies": deps_obj,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _install_node_deps(
        self,
        *,
        sandbox: Sandbox,
        deps: list[str],
        on_log: Optional[Callable[[str], None]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        def dbg(msg: str, level: str = "DEBUG"):
            logger.log(getattr(logging, level), f"[{sandbox.path.name}] {msg}")
            if on_log and _should_emit_to_ui(level):
                _call_on_log(on_log, msg, level)

        deps_clean = [str(d).strip() for d in (deps or []) if str(d).strip()]
        if not deps_clean:
            return

        dbg("Installing dependencies via npm", "INFO")
        stop = Event()
        thr = Thread(
            target=_heartbeat,
            kwargs={
                "stop": stop,
                "on_log": on_log,
                "message": f"[deploy] Installing dependencies via npm ({len(deps_clean)} deps)",
                "interval_s": float(_beat_every_s()),
            },
            daemon=True,
        )
        thr.start()
        try:
            install_env = os.environ.copy()
            for k, v in (env or {}).items():
                if k is None or v is None:
                    continue
                install_env[str(k)] = str(v)

            proc = subprocess.Popen(
                [
                    "npm",
                    "install",
                    "--no-audit",
                    "--no-fund",
                    "--progress=false",
                ],
                cwd=str(sandbox.path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=install_env,
            )
            try:
                if proc.stdout:
                    for line in proc.stdout:
                        s = (line or "").rstrip("\n")
                        if not s:
                            continue
                        if on_log and _should_emit_to_ui("INFO"):
                            _call_on_log(on_log, s, "INFO")
                rc = proc.wait()
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, proc.args)
            finally:
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass
        except FileNotFoundError as e:
            dbg("npm not found in PATH (Node.js runtime missing)", "ERROR")
            raise e
        except subprocess.CalledProcessError as e:
            dbg(f"npm install failed: {e}", "ERROR")
            raise
        finally:
            stop.set()
        dbg("Dependencies installed", "INFO")

    def __init__(self, sandbox_root: str | Path):
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, ServiceProcess] = {}
        self._dep_cache = DependencyCache(self.sandbox_root / ".cache" / "venvs")

    def get_sandbox_path(self, service_name: str) -> Path:
        """Get sandbox path for a service."""
        return self.sandbox_root / service_name

    def create_sandbox(
        self,
        service: ServiceConfig,
        readme_path: Path,
        install_dependencies: bool = True,
        on_log: Optional[Callable[[str], None]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> Sandbox:
        """Create a sandbox for a service from its README."""
        def dbg(msg: str, level: str = "DEBUG"):
            logger.log(getattr(logging, level), f"[{service.name}] {msg}")
            if on_log and _should_emit_to_ui(level):
                _call_on_log(on_log, msg, level)

        def _verify_restored_venv(*, venv_path: Path, deps: list[str], run_cmd: str) -> bool:
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

            try:
                check_env = os.environ.copy()
                for k, v in (env or {}).items():
                    if k is None or v is None:
                        continue
                    check_env[str(k)] = str(v)
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
                    dbg(f"Cached venv verification failed: {out}", "WARNING")
                return False

            return True

        sandbox_path = self.get_sandbox_path(service.name)

        dbg(f"Sandbox root: {_path_debug(self.sandbox_root)}", "DEBUG")
        dbg(f"Sandbox path: {_path_debug(sandbox_path)}", "DEBUG")
        dbg(f"README path: {_path_debug(readme_path)}", "DEBUG")
        dbg(f"UID/EUID/GID: uid={os.getuid()} euid={os.geteuid()} gid={os.getgid()}", "DEBUG")

        if sandbox_path.exists():
            dbg(f"Removing existing sandbox: {sandbox_path}", "INFO")
            shutil.rmtree(sandbox_path)
        sandbox_path.mkdir(parents=True, exist_ok=False)
        dbg(f"Created sandbox dir: {_path_debug(sandbox_path)}", "DEBUG")

        sandbox = Sandbox(sandbox_path)

        readme_content = readme_path.read_text()
        dbg(f"Read README bytes={len(readme_content.encode('utf-8', errors='replace'))}", "DEBUG")
        blocks = parse_blocks(readme_content)

        kind_counts: dict[str, int] = {}
        for b in blocks:
            kind_counts[b.kind] = kind_counts.get(b.kind, 0) + 1
        dbg(f"Parsed markpact blocks: total={len(blocks)} kinds={kind_counts}", "DEBUG")

        deps: list[str] = []
        deps_node: list[str] = []
        run_cmd: str = ""

        for block in blocks:
            if block.kind == "deps":
                if self._is_node_lang(getattr(block, "lang", "")):
                    deps_node.extend(block.body.strip().split("\n"))
                else:
                    deps.extend(block.body.strip().split("\n"))
            elif block.kind == "file":
                file_path = block.get_path() or "main.py"
                dbg(f"Writing file: {file_path} (chars={len(block.body)})", "DEBUG")
                sandbox.write_file(file_path, block.body)
            elif block.kind == "run":
                run_cmd = block.body.strip()

        deps_clean = [d.strip() for d in deps if d.strip()]
        deps_node_clean = [d.strip() for d in deps_node if d.strip()]

        def _dep_name(raw: str) -> str:
            s = (raw or "").strip()
            if not s:
                return ""
            s = s.split(";")[0].strip()  # markers
            s = s.split("[")[0].strip()  # extras
            s = re.split(r"[<>=!~]", s, maxsplit=1)[0].strip()
            return s.lower()
        is_node = self._infer_node_project(blocks=blocks, deps=(deps_node_clean or deps_clean), run_cmd=run_cmd)
        effective_node_deps = deps_node_clean if deps_node_clean else (deps_clean if is_node else [])

        if is_node and effective_node_deps:
            dbg(f"Dependencies detected: count={len(effective_node_deps)}", "INFO")
            self._ensure_package_json(sandbox_path=sandbox.path, service_name=service.name, deps=effective_node_deps)
            dbg(f"Wrote package.json: {_path_debug(sandbox.path / 'package.json')}", "DEBUG")

            if install_dependencies:
                self._install_node_deps(sandbox=sandbox, deps=effective_node_deps, on_log=on_log, env=env)

            return sandbox

        if deps_clean:
            # Always write requirements.txt so the sandbox can be used as a container build context
            dbg(f"Dependencies detected: count={len(deps_clean)}", "INFO")

            run_l = (run_cmd or "").strip().lower()
            dep_names = {_dep_name(d) for d in deps_clean}
            if (run_l.startswith("uvicorn ") or " uvicorn " in f" {run_l} ") and "uvicorn" not in dep_names:
                deps_clean.append("uvicorn")
                dbg("Added implicit dependency: uvicorn (based on run command)", "INFO")
            if (run_l.startswith("gunicorn ") or " gunicorn " in f" {run_l} ") and "gunicorn" not in dep_names:
                deps_clean.append("gunicorn")
                dbg("Added implicit dependency: gunicorn (based on run command)", "INFO")

            sandbox.write_requirements(deps_clean)
            dbg(f"Wrote requirements.txt: {_path_debug(sandbox.path / 'requirements.txt')}", "DEBUG")

            if install_dependencies:
                cached = None
                try:
                    cached = self._dep_cache.get_cached_venv(deps_clean) if self._dep_cache else None
                except Exception:
                    cached = None

                if cached:
                    try:
                        dbg(f"⚡ Cache hit! Reusing venv ({cached.deps_hash})", "INFO")
                        venv_dst = sandbox.path / ".venv"
                        if venv_dst.exists() or venv_dst.is_symlink():
                            try:
                                if venv_dst.is_dir() and not venv_dst.is_symlink():
                                    shutil.rmtree(venv_dst)
                                else:
                                    venv_dst.unlink()
                            except Exception:
                                pass

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
                                "on_log": on_log,
                                "message": f"[deploy] Restoring cached venv ({len(deps_clean)} deps)",
                                "interval_s": float(_beat_every_s()),
                            },
                            daemon=True,
                        )
                        thr.start()
                        _copytree_fast(cached.path, venv_dst)
                        stop.set()
                        dbg(f"Venv restored: {_path_debug(venv_dst)}", "DEBUG")
                        if _verify_restored_venv(venv_path=venv_dst, deps=deps_clean, run_cmd=run_cmd):
                            return sandbox
                        dbg("Cached venv appears corrupted - rebuilding", "WARNING")
                        try:
                            shutil.rmtree(venv_dst)
                        except Exception:
                            pass
                        try:
                            if self._dep_cache:
                                self._dep_cache.invalidate(deps_clean)
                        except Exception:
                            pass
                    except Exception:
                        try:
                            stop.set()
                        except Exception:
                            pass

                dbg(f"Creating venv (.venv) in sandbox", "INFO")
                try:
                    stop = Event()
                    thr = Thread(
                        target=_heartbeat,
                        kwargs={
                            "stop": stop,
                            "on_log": on_log,
                            "message": f"[deploy] Creating venv (.venv) ({len(deps_clean)} deps)",
                            "interval_s": float(_beat_every_s()),
                        },
                        daemon=True,
                    )
                    thr.start()
                    ensure_venv(sandbox, verbose=False)
                    stop.set()
                    dbg(f"Venv status: {_path_debug(sandbox.path / '.venv')}", "DEBUG")
                except Exception as e:
                    try:
                        stop.set()
                    except Exception:
                        pass
                    dbg(f"ensure_venv failed: {e}", "ERROR")
                    raise
                dbg("Installing dependencies via pip", "INFO")
                try:
                    pip_stop = Event()
                    thr = Thread(
                        target=_heartbeat,
                        kwargs={
                            "stop": pip_stop,
                            "on_log": on_log,
                            "message": f"[deploy] Installing dependencies via pip ({len(deps_clean)} deps)",
                            "interval_s": float(_beat_every_s()),
                        },
                        daemon=True,
                    )
                    thr.start()
                    install_env = os.environ.copy()
                    for k, v in (env or {}).items():
                        if k is None or v is None:
                            continue
                        install_env[str(k)] = str(v)

                    pip_path = sandbox.venv_bin / "pip"
                    requirements_path = sandbox.path / "requirements.txt"

                    try:
                        proc = subprocess.Popen(
                            [
                                str(pip_path),
                                "install",
                                "--disable-pip-version-check",
                                "--progress-bar",
                                "off",
                                "-r",
                                str(requirements_path),
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            bufsize=1,
                            env=install_env,
                        )
                        if proc.stdout:
                            for line in proc.stdout:
                                s = (line or "").rstrip("\n")
                                if not s:
                                    continue
                                if on_log:
                                    _call_on_log(on_log, s, "INFO")
                        rc = proc.wait()
                        if rc != 0:
                            raise subprocess.CalledProcessError(rc, proc.args)
                    except subprocess.CalledProcessError as e:
                        dbg(f"pip install failed: {e}", "ERROR")
                        raise
                    finally:
                        try:
                            pip_stop.set()
                        except Exception:
                            pass
                    dbg("Dependencies installed", "INFO")
                    try:
                        self._dep_cache.save_existing_venv(deps_clean, sandbox.path / ".venv", on_progress=on_log)
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        pip_stop.set()
                    except Exception:
                        pass
                    dbg(f"install_deps failed: {e}", "ERROR")
                    raise
        else:
            dbg("No dependencies block found", "DEBUG")

        return sandbox

    def start_service(
        self,
        service: ServiceConfig,
        readme_path: Path,
        env: dict[str, str],
        verbose: bool = True,
        restart_if_running: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
        user_id: Optional[str] = None,
    ) -> ServiceProcess:
        """Start a service in its sandbox.
        
        Args:
            service: Service configuration
            readme_path: Path to README.md with markpact blocks
            env: Environment variables to pass to the service
            verbose: Print status messages
            restart_if_running: If True, stop and restart if already running
            on_log: Callback for detailed logging
            user_id: Optional SaaS user ID for process isolation
        """
        def log(msg: str, level: str = "INFO"):
            logger.log(getattr(logging, level), f"[{service.name}] {msg}")
            if on_log and _should_emit_to_ui(level):
                _call_on_log(on_log, msg, level)
            if verbose and _should_emit_to_ui(level):
                print(msg)
        
        log(f"Starting service: {service.name}", "INFO")
        log(f"Port: {service.port}, README: {readme_path}", "DEBUG")
        log(f"Runner UID/EUID/GID: uid={os.getuid()} euid={os.geteuid()} gid={os.getgid()}", "DEBUG")
        log(f"Sandbox root: {_path_debug(self.sandbox_root)}", "DEBUG")
        log(f"README: {_path_debug(readme_path)}", "DEBUG")
        
        if service.name in self._processes:
            existing = self._processes[service.name]
            if existing.is_running:
                if restart_if_running:
                    log(f"Restarting {service.name}...", "INFO")
                    self.stop_service(service.name)
                    self.clean_sandbox(service.name)
                else:
                    log(f"Service {service.name} already running", "ERROR")
                    raise RuntimeError(f"Service {service.name} is already running")

        # Create sandbox with dependency installation
        log("Creating sandbox and installing dependencies...", "INFO")
        try:
            sandbox = self.create_sandbox(
                service,
                readme_path,
                install_dependencies=True,
                on_log=log,
                env=env,
            )
            log(f"Sandbox created at: {sandbox.path}", "INFO")
        except Exception as e:
            log(f"Failed to create sandbox: {e}", "ERROR")
            logger.exception(f"Sandbox creation failed for {service.name}")
            raise

        readme_content = readme_path.read_text()
        blocks = parse_blocks(readme_content)

        run_command = None
        for block in blocks:
            if block.kind == "run":
                run_command = block.body.strip()
                break

        if not run_command:
            log(f"No run command found in README", "ERROR")
            raise ValueError(f"No run command found in {readme_path}")

        log(f"Run command: {run_command}", "DEBUG")

        full_env = os.environ.copy()
        full_env.update(env)
        
        # Ensure PORT is always set in environment
        full_env["PORT"] = str(service.port)
        full_env["MARKPACT_PORT"] = str(service.port)

        dotenv_env = dict(env or {})
        dotenv_env["PORT"] = str(service.port)
        dotenv_env["MARKPACT_PORT"] = str(service.port)
        _write_dotenv_file(sandbox.path, dotenv_env)

        if sandbox.has_venv():
            venv_bin = str(sandbox.venv_bin)
            full_env["PATH"] = f"{venv_bin}:{full_env.get('PATH', '')}"
            full_env["VIRTUAL_ENV"] = str(sandbox.path / ".venv")
            log(f"Using venv: {sandbox.path / '.venv'}", "DEBUG")
        else:
            log("WARNING: No venv found, using system Python", "WARNING")

        # Expand $PORT in command
        expanded_cmd = run_command.replace("$PORT", str(service.port))
        expanded_cmd = expanded_cmd.replace("${PORT}", str(service.port))
        expanded_cmd = expanded_cmd.replace("${MARKPACT_PORT}", str(service.port))
        expanded_cmd = expanded_cmd.replace("$MARKPACT_PORT", str(service.port))
        
        # Replace hardcoded ports in run command with the requested port
        # This handles cases where LLM generates hardcoded ports like --port 8000
        import re
        port_patterns = [
            (r'--port[=\s]+(\d+)', f'--port {service.port}'),  # --port 8000 or --port=8000
            (r'-p[=\s]+(\d+)', f'-p {service.port}'),          # -p 8000 or -p=8000
            (r':(\d{4,5})(?=\s|$|")', f':{service.port}'),     # :8000 at end of string
        ]
        
        original_cmd = expanded_cmd
        for pattern, replacement in port_patterns:
            match = re.search(pattern, expanded_cmd)
            if match:
                old_port = match.group(1) if match.groups() else None
                if old_port and old_port != str(service.port):
                    log(f"Replacing hardcoded port {old_port} with {service.port}", "INFO")
                    expanded_cmd = re.sub(pattern, replacement, expanded_cmd)
        
        if expanded_cmd != original_cmd:
            log(f"Port-corrected command: {expanded_cmd}", "INFO")
        else:
            log(f"Expanded command: {expanded_cmd}", "DEBUG")
        
        # Remove --reload flag from uvicorn commands in sandbox environments
        # --reload uses multiprocessing which can crash in Docker containers
        if "--reload" in expanded_cmd and "uvicorn" in expanded_cmd:
            expanded_cmd = re.sub(r'\s*--reload\s*', ' ', expanded_cmd)
            log(f"Removed --reload flag (not compatible with sandbox): {expanded_cmd}", "INFO")

        if sandbox.has_venv():
            venv_python = sandbox.venv_bin / "python"
            venv_python_q = shlex.quote(str(venv_python))

            # Prefer venv python for common Python entrypoints. This is more robust than
            # relying on PATH when running under user isolation.
            rewritten = expanded_cmd
            rewritten = re.sub(r"^\s*uvicorn(\s+)", rf"{venv_python_q} -m uvicorn\1", rewritten, count=1)
            rewritten = re.sub(r"^\s*gunicorn(\s+)", rf"{venv_python_q} -m gunicorn\1", rewritten, count=1)
            rewritten = re.sub(r"^\s*python3?(\s+)", rf"{venv_python_q}\1", rewritten, count=1)

            if rewritten != expanded_cmd:
                expanded_cmd = rewritten
                log(f"Rewriting run command to use venv python: {expanded_cmd}", "DEBUG")

        log(f"Starting process...", "INFO")

        # Use user isolation if user_id provided
        preexec = os.setsid
        if user_id:
            try:
                from .user_isolation import get_isolation_manager
                isolation = get_isolation_manager()
                try:
                    can_isolate, reason = isolation.can_isolate()
                    log(f"Isolation capability: can_isolate={can_isolate} reason={reason}", "DEBUG")
                except Exception as e:
                    log(f"Isolation capability check failed: {e}", "WARNING")
                user = isolation.get_or_create_user(user_id)
                log(f"🔒 Running as isolated user: {user.linux_username} (uid={user.linux_uid})", "INFO")
                
                # Update env with user-specific settings
                full_env["HOME"] = str(user.home_dir)
                full_env["USER"] = user.linux_username
                full_env["LOGNAME"] = user.linux_username
                
                # Create preexec function for user switching
                def preexec():
                    os.setsid()
                    if os.geteuid() == 0:
                        os.setgid(user.linux_gid)
                        os.setuid(user.linux_uid)
            except Exception as e:
                log(f"⚠️ User isolation not available: {e} - using sandbox uid", "WARNING")
                if os.geteuid() == 0:
                    uid, gid = _sandbox_fallback_ids()
                    log(f"Sandbox uid fallback: uid={uid} gid={gid}", "DEBUG")
                    try:
                        dotenv_path = sandbox.path / ".env"
                        if dotenv_path.exists():
                            os.chown(dotenv_path, uid, gid)
                    except Exception:
                        pass
                    _chown_sandbox_tree(sandbox.path, uid, gid)

                    def preexec():
                        os.setsid()
                        os.setgid(gid)
                        os.setuid(uid)

        # Always capture stderr for debugging
        # nosec B602: shell=True required - we execute user-defined run commands
        # Input is validated via markpact parsing and sandbox isolation
        process = subprocess.Popen(
            expanded_cmd,
            shell=True,  # nosec B602
            cwd=str(sandbox.path),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec,
        )

        log(f"Process started with PID: {process.pid}", "INFO")

        # Wait briefly for process to start (but don't block too long)
        time.sleep(0.2)
        
        # Check if process died immediately
        poll_result = process.poll()
        if poll_result is not None:
            # Process already died - capture all output
            exit_code = poll_result
            stderr = ""
            stdout = ""
            
            try:
                # Read all output with timeout
                stdout_bytes, stderr_bytes = process.communicate(timeout=2)
                stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
                stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            except Exception as e:
                log(f"Could not read process output: {e}", "WARNING")
                if process.stderr:
                    try:
                        stderr = process.stderr.read().decode('utf-8', errors='replace')
                    except:
                        pass
            
            # Interpret exit code
            if exit_code < 0:
                signal_name = {
                    -9: "SIGKILL",
                    -15: "SIGTERM", 
                    -11: "SIGSEGV",
                    -6: "SIGABRT",
                }.get(exit_code, f"signal {-exit_code}")
                log(f"Process killed by {signal_name} (exit code: {exit_code})", "ERROR")
            else:
                log(f"Process exited with code: {exit_code}", "ERROR")
            
            if stderr:
                log(f"STDERR:\n{stderr[:2000]}", "ERROR")
            if stdout:
                log(f"STDOUT:\n{stdout[:1000]}", "DEBUG")
            
            # Write to error log file
            error_log = LOG_DIR / f"{service.name}_error.log"
            with open(error_log, "w") as f:
                f.write(f"Exit code: {exit_code}\n")
                f.write(f"Command: {expanded_cmd}\n")
                f.write(f"CWD: {sandbox.path}\n")
                f.write(f"Venv: {sandbox.path / '.venv'}\n")
                f.write(f"\n--- STDERR ---\n{stderr}\n")
                f.write(f"\n--- STDOUT ---\n{stdout}\n")
                # List files for debugging
                try:
                    files = list(sandbox.path.glob("*"))
                    f.write(f"\n--- FILES ---\n{[str(f) for f in files]}\n")
                except:
                    pass
            log(f"Error log written to: {error_log}", "DEBUG")

        svc_process = ServiceProcess(
            name=service.name,
            pid=process.pid,
            port=service.port,
            sandbox_path=sandbox.path,
            process=process,
        )

        self._processes[service.name] = svc_process
        
        # Log sandbox contents for debugging
        try:
            files = list(sandbox.path.glob("*"))
            log(f"Sandbox files: {[f.name for f in files]}", "DEBUG")
        except:
            pass
        
        return svc_process

    def stop_service(self, service_name: str, timeout: int = 10) -> bool:
        """Stop a running service."""
        if service_name not in self._processes:
            logger.debug(f"Service {service_name} not in tracked processes")
            return False

        svc = self._processes[service_name]
        old_pid = svc.pid

        if not svc.is_running:
            logger.debug(f"Service {service_name} (PID {old_pid}) already stopped")
            del self._processes[service_name]
            return True

        logger.info(f"Stopping service {service_name} (PID {old_pid})")
        
        try:
            pgid = os.getpgid(old_pid)
            os.killpg(pgid, signal.SIGTERM)
            logger.debug(f"Sent SIGTERM to process group {pgid}")
        except ProcessLookupError:
            logger.debug(f"Process {old_pid} already gone")
            del self._processes[service_name]
            return True
        except OSError as e:
            logger.warning(f"Error getting pgid for {old_pid}: {e}")
            # Try killing just the process
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not svc.is_running:
                break
            time.sleep(0.1)

        if svc.is_running:
            logger.warning(f"Service {service_name} didn't stop gracefully, sending SIGKILL")
            try:
                os.killpg(os.getpgid(old_pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

        del self._processes[service_name]
        
        # Wait for OS to clean up the process
        time.sleep(0.3)
        logger.info(f"Service {service_name} stopped")
        return True

    def stop_all(self, timeout: int = 10) -> None:
        """Stop all running services."""
        for name in list(self._processes.keys()):
            self.stop_service(name, timeout)

    def get_status(self, service_name: str) -> Optional[dict]:
        """Get status of a service."""
        if service_name not in self._processes:
            return None

        svc = self._processes[service_name]
        return {
            "name": svc.name,
            "pid": svc.pid,
            "port": svc.port,
            "running": svc.is_running,
            "uptime": time.time() - svc.started_at,
            "sandbox": str(svc.sandbox_path),
        }

    def get_all_status(self) -> list[dict]:
        """Get status of all services."""
        return [
            self.get_status(name)
            for name in self._processes
            if self.get_status(name)
        ]

    def clean_sandbox(self, service_name: str) -> None:
        """Remove sandbox directory for a service."""
        sandbox_path = self.get_sandbox_path(service_name)
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

    def clean_all(self) -> None:
        """Remove all sandbox directories."""
        if self.sandbox_root.exists():
            shutil.rmtree(self.sandbox_root)
        self.sandbox_root.mkdir(parents=True)

    def create_sandboxes_parallel(
        self,
        services: list[tuple[ServiceConfig, Path]],
        max_workers: int = 4,
        on_complete: Optional[Callable[[str, bool, float], None]] = None,
    ) -> dict[str, Sandbox]:
        """
        Create sandboxes for multiple services in parallel.

        Args:
            services: List of (ServiceConfig, readme_path) tuples
            max_workers: Maximum parallel workers
            on_complete: Callback(name, success, duration)

        Returns:
            Dict of {service_name: Sandbox}
        """
        results: dict[str, Sandbox] = {}
        errors: dict[str, str] = {}
        lock = Lock()

        def create_one(service: ServiceConfig, readme_path: Path) -> tuple[str, Sandbox]:
            sandbox = self.create_sandbox(service, readme_path)
            return service.name, sandbox

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            start_times = {}

            for service, readme_path in services:
                start_times[service.name] = time.time()
                future = executor.submit(create_one, service, readme_path)
                futures[future] = service.name

            for future in as_completed(futures):
                name = futures[future]
                duration = time.time() - start_times[name]

                try:
                    _, sandbox = future.result()
                    with lock:
                        results[name] = sandbox
                    if on_complete:
                        on_complete(name, True, duration)
                except Exception as e:
                    with lock:
                        errors[name] = str(e)
                    if on_complete:
                        on_complete(name, False, duration)

        if errors:
            error_msg = "; ".join(f"{k}: {v}" for k, v in errors.items())
            raise RuntimeError(f"Failed to create sandboxes: {error_msg}")

        return results

    def start_services_parallel(
        self,
        services: list[tuple[ServiceConfig, Path, dict[str, str]]],
        max_workers: int = 4,
        on_complete: Optional[Callable[[str, bool, float], None]] = None,
    ) -> dict[str, ServiceProcess]:
        """
        Start multiple services in parallel.

        Note: Should only be used for services with no inter-dependencies.
        For dependent services, use the orchestrator's wave-based approach.

        Args:
            services: List of (ServiceConfig, readme_path, env) tuples
            max_workers: Maximum parallel workers
            on_complete: Callback(name, success, duration)

        Returns:
            Dict of {service_name: ServiceProcess}
        """
        results: dict[str, ServiceProcess] = {}
        errors: dict[str, str] = {}
        lock = Lock()

        def start_one(
            service: ServiceConfig,
            readme_path: Path,
            env: dict[str, str]
        ) -> tuple[str, ServiceProcess]:
            proc = self.start_service(service, readme_path, env, verbose=False)
            return service.name, proc

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            start_times = {}

            for service, readme_path, env in services:
                start_times[service.name] = time.time()
                future = executor.submit(start_one, service, readme_path, env)
                futures[future] = service.name

            for future in as_completed(futures):
                name = futures[future]
                duration = time.time() - start_times[name]

                try:
                    _, proc = future.result()
                    with lock:
                        results[name] = proc
                    if on_complete:
                        on_complete(name, True, duration)
                except Exception as e:
                    with lock:
                        errors[name] = str(e)
                    if on_complete:
                        on_complete(name, False, duration)

        return results, errors
