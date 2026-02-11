from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = (_PROJECT_ROOT / "src").resolve()
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Load .env from project root so PACTOWN_SANDBOX_ROOT=.pactown is active
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# Resolve relative PACTOWN_SANDBOX_ROOT against project root
_sandbox = os.environ.get("PACTOWN_SANDBOX_ROOT", "")
if _sandbox and not os.path.isabs(_sandbox):
    os.environ["PACTOWN_SANDBOX_ROOT"] = str((_PROJECT_ROOT / _sandbox).resolve())
