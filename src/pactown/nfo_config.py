"""
Centralized nfo logging configuration for pactown.

Usage at project entry point (cli.py, runner_api.py):

    from pactown.nfo_config import setup_logging
    setup_logging()

For decorators (any module):

    from pactown.nfo_config import logged, log_call, catch

    @logged
    class MyService: ...

This configures nfo to:
- Write structured logs to SQLite (queryable)
- Bridge existing stdlib loggers (pactown.sandbox, etc.)
- Auto-instrument all public functions in key modules via auto_log()
- Tag logs with environment/trace_id/version automatically
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

# ---------------------------------------------------------------------------
# Centralized nfo imports — every module uses:
#     from pactown.nfo_config import logged       # class decorator
#     from pactown.nfo_config import log_call      # function decorator
#     from pactown.nfo_config import catch         # exception-safe decorator
#     from pactown.nfo_config import skip          # exclude method from @logged
# If nfo is not installed, all decorators become transparent no-ops.
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])

try:
    from nfo import logged, log_call, catch, skip  # type: ignore[import-untyped]
except ImportError:  # nfo not installed — provide no-op fallbacks
    def logged(cls: Any = None, **kw: Any) -> Any:  # type: ignore[misc]
        return cls if cls is not None else lambda c: c

    def log_call(fn: Any = None, **kw: Any) -> Any:  # type: ignore[misc]
        return fn if fn is not None else lambda f: f

    def catch(fn: Any = None, **kw: Any) -> Any:  # type: ignore[misc]
        return fn if fn is not None else lambda f: f

    def skip(fn: F) -> F:  # type: ignore[misc]
        return fn

_initialized = False

# Modules to auto-instrument with nfo.auto_log().
# All public functions in these modules get @log_call wrapping automatically.
_AUTO_LOG_MODULES = [
    "pactown.sandbox_manager",
    "pactown.service_runner",
    "pactown.orchestrator",
    "pactown.security",
    "pactown.sandbox_helpers",
    "pactown.network",
    "pactown.resolver",
    "pactown.fast_start",
    "pactown.error_context",
    "pactown.generator",
    "pactown.user_isolation",
    "pactown.node_cache",
    "pactown.parallel",
    "pactown.iac",
    "pactown.targets",
    "pactown.platform",
    "pactown.events",
    "pactown.llm",
]

# Stdlib logger names to bridge to nfo sinks (captures logging.getLogger() calls).
_BRIDGE_MODULES = [
    "pactown.sandbox",
    "pactown.runner_api",
    "pactown.service_runner",
    "pactown.security",
    "pactown.orchestrator",
    "pactown.builders",
    "pactown.events",
    "pactown.llm",
]


def setup_logging(
    *,
    log_dir: Optional[str] = None,
    level: str = "DEBUG",
    enable_sqlite: bool = True,
    enable_csv: bool = False,
    enable_markdown: bool = False,
    auto_instrument: bool = True,
) -> None:
    """
    Initialize nfo logging for pactown.

    Call once from each entry point **after** all local imports so that
    ``auto_log_by_name`` can patch already-loaded modules.

    Args:
        log_dir: Directory for log files. Defaults to PACTOWN_LOG_DIR or /tmp/pactown-logs.
        level: Minimum log level.
        enable_sqlite: Write logs to SQLite database.
        enable_csv: Write logs to CSV file.
        enable_markdown: Write logs to Markdown file.
        auto_instrument: If True, auto_log() all key modules (no decorators needed).
    """
    global _initialized

    if _initialized:
        return

    try:
        from nfo import configure, auto_log_by_name  # type: ignore[import-untyped]
    except ImportError:
        return

    log_dir = log_dir or os.environ.get(
        "PACTOWN_LOG_DIR", str(Path(tempfile.gettempdir()) / "pactown-logs")
    )
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    sinks: list[str] = []
    if enable_sqlite:
        sinks.append(f"sqlite:{log_path / 'pactown.db'}")
    if enable_csv:
        sinks.append(f"csv:{log_path / 'pactown.csv'}")
    if enable_markdown:
        sinks.append(f"md:{log_path / 'pactown.md'}")

    configure(
        name="pactown",
        level=level,
        sinks=sinks if sinks else None,
        modules=_BRIDGE_MODULES if sinks else None,
        propagate_stdlib=True,
        environment=os.environ.get("PACTOWN_ENV"),
        version=os.environ.get("PACTOWN_VERSION"),
    )

    # Auto-instrument already-imported modules
    if auto_instrument and sinks:
        auto_log_by_name(*_AUTO_LOG_MODULES, level=level)

    _initialized = True
