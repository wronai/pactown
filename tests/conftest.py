from __future__ import annotations

import asyncio
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
import pytest

# Load anyio when available (Makefile / full dev install).
pytest_plugins = ["anyio"]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_F = TypeVar("_F", bound=Callable[..., Any])


def async_test(fn: _F) -> Callable[..., Any]:
    """Run an async test body via asyncio.run — no pytest-asyncio/anyio plugin required."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


@pytest.fixture
def anyio_backend():
    """Run @pytest.mark.anyio tests on asyncio when the anyio plugin is active."""
    return "asyncio"
_SRC = (_PROJECT_ROOT / "src").resolve()
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Load .env from project root so PACTOWN_SANDBOX_ROOT=.pactown is active
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# Resolve relative PACTOWN_SANDBOX_ROOT against project root
_sandbox = os.environ.get("PACTOWN_SANDBOX_ROOT", "")
if _sandbox and not os.path.isabs(_sandbox):
    os.environ["PACTOWN_SANDBOX_ROOT"] = str((_PROJECT_ROOT / _sandbox).resolve())
