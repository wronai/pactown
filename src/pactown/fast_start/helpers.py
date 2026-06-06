"""Fast-start subprocess and heartbeat helpers."""
import os
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Callable, Dict, List, Optional

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

