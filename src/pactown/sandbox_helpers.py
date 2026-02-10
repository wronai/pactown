"""Shared helper utilities for sandbox operations.

Extracted from sandbox_manager.py to reduce file size and allow
independent reuse by service_runner.py and other modules.
"""

import inspect
import logging
import os
import re
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

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


def _call_on_log(on_log: Optional[Callable[..., None]], msg: str, level: str) -> None:
    if not on_log:
        return
    try:
        sig = inspect.signature(on_log)
        params = list(sig.parameters.values())
        accepts = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params) or len(params) >= 2
    except Exception:
        accepts = False
    if accepts:
        on_log(msg, level)
    else:
        on_log(msg)


# ---------------------------------------------------------------------------
# Environment sanitisation
# ---------------------------------------------------------------------------

_SENSITIVE_ENV_KEY_RE = re.compile(r"(?:^|_)(?:API_KEY|SECRET|PASSWORD|TOKEN|PRIVATE_KEY)(?:$|_)", re.IGNORECASE)

_BASE_INHERITED_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PIP_DISABLE_PIP_VERSION_CHECK",
    "PIP_NO_CACHE_DIR",
}

_BASE_INHERITED_ENV_PREFIXES = (
    "LC_",
)


def _filter_runtime_env(explicit_env: Optional[dict[str, str]]) -> dict[str, str]:
    src = dict(explicit_env or {})
    deny_keys = {
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_DEFAULT_TIMEOUT",
        "PIP_RETRIES",
        "NPM_CONFIG_REGISTRY",
        "DOCKER_REGISTRY_MIRROR",
        "ACQUIRE::HTTP::PROXY",
        "ACQUIRE::HTTPS::PROXY",
    }
    deny_prefixes = (
        "PACTOWN_",
    )
    out: dict[str, str] = {}
    for k, v in src.items():
        if k is None or v is None:
            continue
        kk = str(k)
        if kk in {"PORT", "MARKPACT_PORT"}:
            out[kk] = str(v)
            continue
        if kk in deny_keys:
            continue
        if any(kk.startswith(p) for p in deny_prefixes):
            continue
        out[kk] = str(v)
    return out


def _sanitize_inherited_env(parent_env: Optional[dict[str, str]], explicit_env: Optional[dict[str, str]] = None) -> dict[str, str]:
    parent = dict(parent_env or {})
    raw_flag = str(os.environ.get("PACTOWN_INHERIT_SENSITIVE_ENV", "") or "").strip().lower()
    if raw_flag in {"1", "true", "yes", "on"}:
        return parent

    keep = {str(k) for k in (explicit_env or {}).keys() if k is not None}
    out: dict[str, str] = {}
    for k, v in parent.items():
        kk = str(k)
        if kk in keep:
            out[kk] = str(v)
            continue
        if kk in _BASE_INHERITED_ENV_KEYS or any(kk.startswith(p) for p in _BASE_INHERITED_ENV_PREFIXES):
            out[kk] = str(v)

    for k in list(out.keys()):
        if k in keep:
            continue
        try:
            if _SENSITIVE_ENV_KEY_RE.search(str(k)):
                out.pop(k, None)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# .env file helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Heartbeat for long operations
# ---------------------------------------------------------------------------

def _heartbeat(
    *,
    stop,  # threading.Event
    on_log: Optional[Callable[..., None]],
    message: str,
    interval_s: float = 1.0,
) -> None:
    import time
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


# ---------------------------------------------------------------------------
# Path debugging
# ---------------------------------------------------------------------------

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
