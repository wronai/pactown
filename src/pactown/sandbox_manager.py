"""Sandbox manager for pactown services."""

import json
import logging
import os
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
from .markpact_blocks import extract_run_command, parse_blocks
from .fast_start import DependencyCache
from .sandbox_helpers import (  # noqa: F401 – re-exported for backward compat
    _beat_every_s,
    _call_on_log,
    _filter_runtime_env,
    _heartbeat,
    _path_debug,
    _sanitize_inherited_env,
    _should_emit_to_ui,
    _write_dotenv_file,
)

# Configure detailed logging
logger = logging.getLogger("pactown.sandbox")
logger.setLevel(logging.DEBUG)

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


def _detect_web_preview_needed(
    expanded_cmd: str,
    target_cfg: "Optional[Any]",
    full_env: dict[str, str],
    sandbox_path: Path,
) -> bool:
    """Return True when a desktop/mobile app should be served via HTTP instead of launched natively.

    Conditions:
    - The target is desktop or mobile (from markpact:target block), OR
      the run command is a known native launcher (electron, capacitor, etc.)
    - No DISPLAY is set (headless server)
    - xvfb-run is not available
    """
    cmd_lower = expanded_cmd.lower()

    # Detect native desktop/mobile commands (always treated as native)
    _native_cmd_patterns = (
        "npx electron",
        "electron .",
        "npx cap run",
        "npx cap open",
        "npx tauri dev",
        "flutter run",
        "npx react-native run",
    )

    is_native_cmd = any(p in cmd_lower for p in _native_cmd_patterns)

    # For python main.py, only treat as native if target says desktop/mobile
    if not is_native_cmd and "python main.py" in cmd_lower:
        if target_cfg and hasattr(target_cfg, "is_buildable") and target_cfg.is_buildable:
            is_native_cmd = True

    # Also check via target_cfg
    if not is_native_cmd and target_cfg:
        if hasattr(target_cfg, "is_buildable") and target_cfg.is_buildable:
            fw = getattr(target_cfg, "framework", "") or ""
            if fw.lower() in ("electron", "tauri", "capacitor", "react-native", "flutter", "kivy", "pyinstaller", "tkinter", "pyqt"):
                is_native_cmd = True

    if not is_native_cmd:
        return False

    # If DISPLAY is available, no need for web preview
    if full_env.get("DISPLAY"):
        return False

    # If xvfb-run is available, prefer that for Electron
    if shutil.which("xvfb-run"):
        return False

    return True


# ── System dependency auto-install ──────────────────────────────────
# Maps framework names and Python imports to apt packages that must be
# present on the host for the app to run.  Called before starting a
# service so that *all* dependencies are resolved dynamically.

_FRAMEWORK_SYSTEM_DEPS: dict[str, list[str]] = {
    # Python GUI toolkits
    "tkinter":     ["python3-tk"],
    "pyinstaller": ["python3-tk"],          # common tkinter dependency
    "pyqt":        ["python3-pyqt5"],
    # Electron / Node desktop
    "electron":    ["libgtk-3-0", "libnotify4", "libnss3", "libxss1",
                    "libasound2t64", "libatk-bridge2.0-0"],
    "tauri":       ["libgtk-3-dev", "libwebkit2gtk-4.1-dev", "libayatana-appindicator3-dev"],
    # Mobile
    "kivy":        ["python3-sdl2", "libsdl2-dev", "libsdl2-image-dev",
                    "libsdl2-mixer-dev", "libsdl2-ttf-dev"],
}

# Extra mapping: Python import → apt package (for import errors)
_IMPORT_TO_APT: dict[str, str] = {
    "tkinter":   "python3-tk",
    "_tkinter":  "python3-tk",
    "PyQt5":     "python3-pyqt5",
    "gi":        "python3-gi",
    "sdl2":      "python3-sdl2",
}


def _install_system_deps(
    framework: str,
    log: Callable[[str, str], None],
) -> None:
    """Install system (apt) packages required by *framework* if missing.

    Runs ``apt-get install -y`` with ``--no-install-recommends`` to keep
    the footprint small.  Non-fatal: logs a warning on failure so that
    the service can still attempt to start (or fall back to web preview).
    """
    pkgs = _FRAMEWORK_SYSTEM_DEPS.get(framework.lower(), [])
    if not pkgs:
        return

    # Quick check: skip if dpkg says all packages are installed
    missing: list[str] = []
    for pkg in pkgs:
        try:
            result = subprocess.run(
                ["dpkg", "-s", pkg],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                missing.append(pkg)
        except Exception:
            missing.append(pkg)

    if not missing:
        return

    log(f"📦 Installing system dependencies: {', '.join(missing)}", "INFO")

    # Prefer PACTOWN_APT_PROXY if configured (local cache)
    apt_env = os.environ.copy()
    apt_proxy = os.environ.get("PACTOWN_APT_PROXY")
    if apt_proxy:
        apt_env["http_proxy"] = apt_proxy
        apt_env["https_proxy"] = apt_proxy

    try:
        subprocess.run(
            ["apt-get", "update", "-qq"],
            capture_output=True, timeout=60, env=apt_env,
        )
        result = subprocess.run(
            ["apt-get", "install", "-y", "--no-install-recommends", *missing],
            capture_output=True, timeout=120, env=apt_env,
        )
        if result.returncode == 0:
            log(f"✅ System dependencies installed: {', '.join(missing)}", "INFO")
        else:
            stderr = result.stderr.decode(errors="replace")[:300]
            log(f"⚠️ apt-get install failed (rc={result.returncode}): {stderr}", "WARNING")
    except FileNotFoundError:
        log("⚠️ apt-get not found – skipping system dependency install", "WARNING")
    except subprocess.TimeoutExpired:
        log("⚠️ apt-get timed out – skipping system dependency install", "WARNING")
    except Exception as e:
        log(f"⚠️ System dependency install failed: {e}", "WARNING")


def _inject_electron_web_polyfill(
    serve_dir: Path,
    target_cfg: "Optional[Any]",
    log: Callable[[str, str], None],
) -> None:
    """Inject a localStorage-backed ``window.api`` polyfill into index.html.

    Electron apps use a preload script that exposes ``window.api`` for IPC
    communication (e.g. ``window.api.getNotes()``).  In web-preview mode there
    is no Electron runtime, so those calls crash with *"window.api is
    undefined"*.  This function detects Electron projects and prepends a small
    ``<script>`` shim that proxies every ``window.api.*`` call to localStorage
    so the app remains functional in the browser.
    """
    framework = getattr(target_cfg, "framework", "").lower() if target_cfg else ""
    is_electron = framework == "electron"

    # Also detect Electron by the presence of main.js + preload.js
    if not is_electron:
        parent = serve_dir.parent if serve_dir.name in ("dist", "build", "www", "public") else serve_dir
        if (parent / "main.js").exists() and (parent / "package.json").exists():
            try:
                pkg_text = (parent / "package.json").read_text()
                if '"electron"' in pkg_text or "'electron'" in pkg_text:
                    is_electron = True
            except Exception:
                pass

    if not is_electron:
        return

    index_html = serve_dir / "index.html"
    if not index_html.exists():
        return

    html = index_html.read_text()

    # Don't inject twice
    if "window.api polyfill" in html or "__pactown_api_polyfill" in html:
        return

    polyfill = """\
<script>
/* window.api polyfill for Electron web-preview mode (pactown) */
if (typeof window.api === 'undefined') {
  (function() {
    var STORAGE_PREFIX = '__pactown_api_';
    function _key(name) { return STORAGE_PREFIX + name; }
    function _getJSON(key, fallback) {
      try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
      catch(e) { return fallback; }
    }
    function _setJSON(key, val) {
      try { localStorage.setItem(key, JSON.stringify(val)); } catch(e) {}
    }
    window.api = new Proxy({}, {
      get: function(_target, prop) {
        /* Common Electron IPC patterns – localStorage backed */
        if (prop === 'getNotes' || prop === 'getItems' || prop === 'getList' || prop === 'getTodos') {
          return function() { return Promise.resolve(_getJSON(_key(prop), [])); };
        }
        if (prop === 'getNote' || prop === 'getItem') {
          return function(id) {
            var items = _getJSON(_key('getNotes'), _getJSON(_key('getItems'), []));
            return Promise.resolve(items.find(function(i) { return i.id === id; }) || null);
          };
        }
        if (prop === 'saveNote' || prop === 'addNote' || prop === 'saveItem' || prop === 'addItem' || prop === 'addTodo') {
          return function(item) {
            var listKey = _key('getNotes');
            var items = _getJSON(listKey, []);
            if (!item.id) item.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
            if (!item.createdAt) item.createdAt = new Date().toISOString();
            items.push(item);
            _setJSON(listKey, items);
            return Promise.resolve(item);
          };
        }
        if (prop === 'deleteNote' || prop === 'deleteItem' || prop === 'deleteTodo') {
          return function(id) {
            var listKey = _key('getNotes');
            var items = _getJSON(listKey, []);
            _setJSON(listKey, items.filter(function(i) { return i.id !== id; }));
            return Promise.resolve(true);
          };
        }
        if (prop === 'updateNote' || prop === 'updateItem') {
          return function(id, data) {
            var listKey = _key('getNotes');
            var items = _getJSON(listKey, []);
            var idx = items.findIndex(function(i) { return i.id === id; });
            if (idx >= 0) { Object.assign(items[idx], data); _setJSON(listKey, items); }
            return Promise.resolve(idx >= 0 ? items[idx] : null);
          };
        }
        /* Generic fallback: store/retrieve by method name */
        if (prop.startsWith('get')) {
          return function() { return Promise.resolve(_getJSON(_key(prop), null)); };
        }
        if (prop.startsWith('set') || prop.startsWith('save') || prop.startsWith('add')) {
          return function(val) { _setJSON(_key(prop), val); return Promise.resolve(val); };
        }
        /* Catch-all: return a no-op async function */
        return function() {
          console.warn('[pactown web-preview] window.api.' + prop + ' called – no Electron IPC available');
          return Promise.resolve(null);
        };
      }
    });
    console.info('[pactown] Electron IPC polyfill active – using localStorage');
  })();
}
</script>
"""

    # Inject right after <head> (or at top if no <head>)
    if "<head>" in html:
        html = html.replace("<head>", "<head>\n" + polyfill, 1)
    elif "<HEAD>" in html:
        html = html.replace("<HEAD>", "<HEAD>\n" + polyfill, 1)
    elif "<html>" in html or "<HTML>" in html:
        tag = "<html>" if "<html>" in html else "<HTML>"
        html = html.replace(tag, tag + "\n<head>\n" + polyfill + "</head>", 1)
    else:
        html = polyfill + html

    index_html.write_text(html)
    log("📦 Injected Electron IPC polyfill (window.api → localStorage)", "INFO")


def _build_web_preview_cmd(
    sandbox_path: Path,
    port: int,
    target_cfg: "Optional[Any]",
    log: Callable[[str, str], None],
) -> Optional[str]:
    """Build a command that serves the app's web assets via HTTP on the given port.

    Tries in order:
    1. npx serve (if node_modules exists or npm is available)
    2. python -m http.server (always available)

    Returns None if no suitable server can be determined.
    """
    # Find the directory containing web assets to serve
    serve_dir = _find_web_assets_dir(sandbox_path)
    log(f"Web preview: serving from {serve_dir}", "DEBUG")
    
    # For Python desktop apps (tkinter, pyinstaller) without web assets, create a fallback HTML
    if not (serve_dir / "index.html").exists():
        framework = getattr(target_cfg, "framework", "").lower() if target_cfg else ""
        if framework in ("tkinter", "pyinstaller", "pyqt"):
            log("Creating fallback HTML for Python desktop app", "INFO")
            fallback_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Desktop App - Web Preview</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 40px; text-align: center; }}
        .notice {{ background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 20px; margin: 20px auto; max-width: 600px; }}
        .error {{ background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }}
        h1 {{ color: #333; }}
        code {{ background: #f8f9fa; padding: 2px 6px; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>🖥️ Desktop App Preview</h1>
    <div class="notice">
        <p>This is a <strong>{framework}</strong> desktop application.</p>
        <p>Desktop apps require a graphical display server and cannot run directly in a browser.</p>
        <p>To run this app natively, install it on your local machine:</p>
        <pre><code>pactown build README.md</code></pre>
    </div>
    <div class="notice error">
        <p><strong>Error:</strong> The app failed to start because tkinter libraries are missing.</p>
        <p>On Ubuntu/Debian, install with: <code>sudo apt install python3-tk</code></p>
    </div>
</body>
</html>"""
            (serve_dir / "index.html").write_text(fallback_html)

    # Inject window.api polyfill for Electron apps running in web preview mode.
    # Electron preload scripts expose window.api for IPC; in the browser we
    # fall back to a localStorage-backed shim so the app doesn't crash.
    _inject_electron_web_polyfill(serve_dir, target_cfg, log)

    # Prefer npx serve for Node.js projects (better MIME types, SPA support)
    node_modules = sandbox_path / "node_modules"
    if node_modules.is_dir() or shutil.which("npx"):
        # Install serve if not already present
        serve_bin = node_modules / ".bin" / "serve"
        if not serve_bin.exists():
            log("Installing 'serve' for web preview...", "INFO")
            try:
                subprocess.run(
                    ["npm", "install", "--no-save", "--no-audit", "--no-fund", "serve"],
                    cwd=str(sandbox_path),
                    capture_output=True,
                    timeout=60,
                )
            except Exception as e:
                log(f"Could not install serve: {e}", "WARNING")

        serve_bin = node_modules / ".bin" / "serve"
        if serve_bin.exists():
            rel = os.path.relpath(serve_dir, sandbox_path) if serve_dir != sandbox_path else "."
            return f"npx serve -s {shlex.quote(rel)} -l {port} --no-clipboard"

    # Fallback: python -m http.server
    python_bin = shutil.which("python3") or shutil.which("python") or "python3"
    venv_python = sandbox_path / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_bin = str(venv_python)
    rel = os.path.relpath(serve_dir, sandbox_path) if serve_dir != sandbox_path else "."
    return f"{shlex.quote(python_bin)} -m http.server {port} --directory {shlex.quote(rel)} --bind 0.0.0.0"


def _find_web_assets_dir(sandbox_path: Path) -> Path:
    """Locate the directory containing the app's web assets (index.html, etc.).

    Search order:
    1. www/          (Capacitor convention)
    2. dist/         (common build output)
    3. build/        (CRA convention)
    4. public/       (static assets)
    5. src/          (source with index.html)
    6. sandbox root  (fallback)
    """
    for subdir in ("www", "dist", "build", "public", "src"):
        candidate = sandbox_path / subdir
        if candidate.is_dir() and (candidate / "index.html").exists():
            return candidate

    # If index.html is at root, serve from root
    if (sandbox_path / "index.html").exists():
        return sandbox_path

    # Last resort: serve from root anyway (user might have other HTML files)
    return sandbox_path


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
            install_env = _sanitize_inherited_env(os.environ.copy(), env)
            for k, v in (env or {}).items():
                if k is None or v is None:
                    continue
                install_env[str(k)] = str(v)

            # Shared npm cache across sandboxes – avoids re-downloading packages
            npm_cache = self.sandbox_root / ".cache" / "npm"
            npm_cache.mkdir(parents=True, exist_ok=True)
            install_env.setdefault("npm_config_cache", str(npm_cache))

            proc = subprocess.Popen(
                [
                    "npm",
                    "install",
                    "--no-audit",
                    "--no-fund",
                    "--progress=false",
                    "--prefer-offline",
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
        from .node_cache import NodeModulesCache
        self._node_cache = NodeModulesCache(self.sandbox_root / ".cache" / "node_modules")

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

        def _write_iac(*, is_node: bool, python_deps: list[str], node_deps: list[str], run_cmd: str) -> None:
            try:
                from .iac import write_sandbox_iac

                write_sandbox_iac(
                    service_name=service.name,
                    readme_path=readme_path,
                    sandbox_path=sandbox.path,
                    port=service.port,
                    run_cmd=run_cmd,
                    is_node=is_node,
                    python_deps=python_deps,
                    node_deps=node_deps,
                    health_path=service.health_check or "/",
                    env_keys=list((env or {}).keys()),
                    env=None,
                )
            except Exception as e:
                dbg(f"Failed to write IaC artifacts: {e}", "WARNING")

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
                check_env = _sanitize_inherited_env(os.environ.copy(), env)
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

        # Read README *before* removing the sandbox dir – the readme file
        # may live inside the sandbox path (e.g. when the caller writes it
        # to sandbox_root/service_name/README.md).
        readme_content = readme_path.read_text()

        if sandbox_path.exists():
            dbg(f"Removing existing sandbox: {sandbox_path}", "INFO")
            shutil.rmtree(sandbox_path)
        sandbox_path.mkdir(parents=True, exist_ok=False)
        dbg(f"Created sandbox dir: {_path_debug(sandbox_path)}", "DEBUG")

        sandbox = Sandbox(sandbox_path)
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

        if is_node:
            if effective_node_deps:
                dbg(f"Dependencies detected: count={len(effective_node_deps)}", "INFO")
            self._ensure_package_json(sandbox_path=sandbox.path, service_name=service.name, deps=effective_node_deps)
            dbg(f"Wrote package.json: {_path_debug(sandbox.path / 'package.json')}", "DEBUG")

            if install_dependencies and effective_node_deps:
                self._install_node_deps(sandbox=sandbox, deps=effective_node_deps, on_log=on_log, env=env)

            _write_iac(is_node=True, python_deps=[], node_deps=effective_node_deps, run_cmd=run_cmd)
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
                            _write_iac(is_node=False, python_deps=deps_clean, node_deps=[], run_cmd=run_cmd)
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
                    install_env = _sanitize_inherited_env(os.environ.copy(), env)
                    for k, v in (env or {}).items():
                        if k is None or v is None:
                            continue
                        install_env[str(k)] = str(v)

                    pip_path = sandbox.venv_bin / "pip"
                    requirements_path = sandbox.path / "requirements.txt"

                    pip_flags: list[str] = []
                    try:
                        t = str(install_env.get("PIP_DEFAULT_TIMEOUT") or "").strip()
                        if t:
                            pip_flags.extend(["--timeout", t])
                    except Exception:
                        pass
                    try:
                        r = str(install_env.get("PIP_RETRIES") or "").strip()
                        if r:
                            pip_flags.extend(["--retries", r])
                    except Exception:
                        pass

                    try:
                        proc = subprocess.Popen(
                            [
                                str(pip_path),
                                "install",
                                "--disable-pip-version-check",
                                "--progress-bar",
                                "off",
                                *pip_flags,
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

        _write_iac(is_node=False, python_deps=deps_clean, node_deps=[], run_cmd=run_cmd)
        return sandbox

    def build_service(
        self,
        service: ServiceConfig,
        readme_path: Path,
        *,
        env: Optional[dict[str, str]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> "BuildResult":
        """Build a desktop or mobile application from its markpact README.

        Unlike ``start_service`` (which launches a long-running server process),
        ``build_service`` runs a one-shot build command and returns a
        ``BuildResult`` with artifact paths.

        Works for *any* target (web build steps are supported too) but is
        primarily intended for ``desktop`` and ``mobile`` targets defined via a
        ``markpact:target`` block.
        """
        from .builders import get_builder_for_target, BuildResult
        from .markpact_blocks import extract_target_config, extract_build_cmd
        from .targets import TargetConfig

        def dbg(msg: str, level: str = "DEBUG"):
            logger.log(getattr(logging, level), f"[{service.name}] {msg}")
            if on_log and _should_emit_to_ui(level):
                _call_on_log(on_log, msg, level)

        dbg(f"Building service: {service.name} (target={service.target})", "INFO")

        # Read README *before* create_sandbox, which may delete the directory
        # containing readme_path (when it lives inside the sandbox root).
        readme_content = readme_path.read_text()

        # Pre-parse blocks once – reused below to avoid double-parsing.
        blocks = parse_blocks(readme_content)
        target_cfg = extract_target_config(blocks)

        if target_cfg is None:
            target_cfg = TargetConfig.from_dict({
                "platform": service.target,
                "framework": service.framework,
                "targets": service.build_targets,
            })

        # Desktop/mobile builds don't need Python deps installed (pip/venv).
        # Node deps are handled separately after scaffold.
        need_python_deps = target_cfg.is_web

        # 1. Create sandbox (write files; optionally install Python deps)
        sandbox = self.create_sandbox(
            service,
            readme_path,
            install_dependencies=need_python_deps,
            on_log=on_log,
            env=env,
        )
        dbg(f"Sandbox created at: {sandbox.path}", "INFO")

        # 2. Resolve build command: explicit markpact:build > service config > framework default
        build_cmd = extract_build_cmd(blocks) or service.build_cmd

        # 4. Get builder, scaffold, build
        builder = get_builder_for_target(target_cfg)
        dbg(f"Using builder: {builder.platform_name} framework={target_cfg.framework}", "INFO")

        app_name = target_cfg.app_name or service.name
        extra_scaffold: dict[str, Any] = dict(target_cfg.extra)
        if target_cfg.app_id:
            extra_scaffold["app_id"] = target_cfg.app_id
        if target_cfg.window_width:
            extra_scaffold["window_width"] = target_cfg.window_width
        if target_cfg.window_height:
            extra_scaffold["window_height"] = target_cfg.window_height
        if target_cfg.icon:
            extra_scaffold["icon"] = target_cfg.icon
        if target_cfg.fullscreen:
            extra_scaffold["fullscreen"] = target_cfg.fullscreen

        builder.scaffold(
            sandbox.path,
            framework=target_cfg.framework or "",
            app_name=app_name,
            extra=extra_scaffold,
            on_log=on_log,
        )

        # 5. Install node deps added by scaffold (e.g. electron, electron-builder)
        pkg_json = sandbox.path / "package.json"
        if pkg_json.exists():
            from .targets import get_framework_meta
            meta = get_framework_meta(target_cfg.framework or "")
            if meta and meta.needs_node:
                pkg_content = pkg_json.read_text()
                # Try to restore node_modules from cache (hardlink-copy, ~0.5s)
                cache_hit = False
                try:
                    cache_hit = self._node_cache.restore(pkg_content, sandbox.path, on_log=on_log)
                except Exception:
                    pass

                if not cache_hit:
                    dbg("Installing node dependencies after scaffold", "INFO")
                    self._install_node_deps(
                        sandbox=sandbox,
                        deps=[],  # deps already in package.json – npm install reads it
                        on_log=on_log,
                        env=env,
                    )
                    # Cache the installed node_modules for future builds
                    try:
                        self._node_cache.save(pkg_content, sandbox.path, on_log=on_log)
                    except Exception:
                        pass
                else:
                    dbg("⚡ node_modules restored from cache", "INFO")

        # 6. Prepare build env – share caches across builds
        build_env = dict(env or {})
        eb_cache = self.sandbox_root / ".cache" / "electron-builder"
        eb_cache.mkdir(parents=True, exist_ok=True)
        build_env.setdefault("ELECTRON_BUILDER_CACHE", str(eb_cache))

        result = builder.build(
            sandbox.path,
            build_cmd=build_cmd,
            framework=target_cfg.framework or "",
            targets=target_cfg.effective_build_targets(),
            env=build_env,
            on_log=on_log,
        )

        if result.success:
            dbg(f"Build succeeded: {len(result.artifacts)} artifact(s)", "INFO")
        else:
            dbg(f"Build failed: {result.message}", "ERROR")

        return result

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

        # Run desktop/mobile scaffold if a markpact:target block is present.
        # This ensures Electron gets a proper package.json ("main" field) and
        # main.js even though _ensure_package_json already wrote a minimal one.
        from .markpact_blocks import extract_target_config
        target_cfg = extract_target_config(blocks)
        if target_cfg is not None and target_cfg.is_buildable:
            try:
                from .builders import get_builder_for_target
                builder = get_builder_for_target(target_cfg)
                app_name = target_cfg.app_name or service.name
                extra_scaffold: dict = dict(target_cfg.extra)
                if target_cfg.app_id:
                    extra_scaffold["app_id"] = target_cfg.app_id
                if target_cfg.window_width:
                    extra_scaffold["window_width"] = target_cfg.window_width
                if target_cfg.window_height:
                    extra_scaffold["window_height"] = target_cfg.window_height
                builder.scaffold(
                    sandbox.path,
                    framework=target_cfg.framework or "",
                    app_name=app_name,
                    extra=extra_scaffold,
                    on_log=log,
                )
                log(f"Scaffolded {builder.platform_name} app (framework={target_cfg.framework})", "INFO")
            except Exception as e:
                log(f"Desktop/mobile scaffold failed (non-fatal): {e}", "WARNING")

        # Auto-install system dependencies for desktop/mobile frameworks
        if target_cfg is not None and target_cfg.framework:
            _install_system_deps(target_cfg.framework, log)

        run_command = extract_run_command(blocks)

        if not run_command:
            log(f"No run command found in README", "ERROR")
            raise ValueError(f"No run command found in {readme_path}")

        log(f"Run command: {run_command}", "DEBUG")

        runtime_env = _filter_runtime_env(env)
        full_env = _sanitize_inherited_env(os.environ.copy(), runtime_env)
        full_env.update(runtime_env)
        
        # Log env keys for debugging
        log(f"Environment keys passed to process: {list(runtime_env.keys())}", "DEBUG")
        
        # Ensure PORT is always set in environment
        full_env["PORT"] = str(service.port)
        full_env["MARKPACT_PORT"] = str(service.port)

        dotenv_env = dict(runtime_env or {})
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

        # Web-preview mode for desktop/mobile apps on headless servers.
        # Instead of launching the native app (Electron, Capacitor, etc.)
        # serve the web assets via HTTP so the app is accessible in a browser
        # under its subdomain.
        _needs_web_preview = _detect_web_preview_needed(
            expanded_cmd, target_cfg, full_env, sandbox.path
        )
        if _needs_web_preview:
            preview_cmd = _build_web_preview_cmd(
                sandbox.path, service.port, target_cfg, log
            )
            if preview_cmd:
                log(f"🌐 Web preview mode – serving app in browser instead of native launch", "INFO")
                log(f"Preview command: {preview_cmd}", "DEBUG")
                expanded_cmd = preview_cmd

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
                
                if os.geteuid() == 0:
                    try:
                        dotenv_path = sandbox.path / ".env"
                        if dotenv_path.exists():
                            os.chown(dotenv_path, user.linux_uid, user.linux_gid)
                    except Exception:
                        pass
                    _chown_sandbox_tree(sandbox.path, user.linux_uid, user.linux_gid)
                
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
                    except Exception:
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
                except Exception:
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
        except Exception:
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
