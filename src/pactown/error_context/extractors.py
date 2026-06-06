import re
from pathlib import Path
from typing import Dict, List, Optional


_TRACE_ID_PATTERN = re.compile(
    r"(trace_id|traceid|trace-id|request_id|requestid)[=:\s]+([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)

_PY_TRACE_FILE_PATTERN = re.compile(
    r"File\s+\"([^\"]+)\"\s*,\s*line\s*(\d+)",
    re.IGNORECASE,
)

_GENERIC_PATH_PATTERN = re.compile(r"(/[^\s:\]\)\(\[\{\}<>\"']+\.(?:py|js|ts|tsx|java|go|rs|php|rb))")


def truncate_text(value: str, *, max_chars: int) -> str:
    s = value or ""
    if max_chars <= 0:
        return ""
    if len(s) <= max_chars:
        return s
    return s[-max_chars:]


def extract_trace_ids(text: str) -> List[str]:
    ids: List[str] = []
    seen = set()
    for m in _TRACE_ID_PATTERN.finditer(text or ""):
        v = (m.group(2) or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        ids.append(v)
    return ids


def extract_file_paths(text: str) -> List[str]:
    paths: List[str] = []

    for m in _PY_TRACE_FILE_PATTERN.finditer(text or ""):
        p = (m.group(1) or "").strip()
        if p:
            paths.append(p)

    for m in _GENERIC_PATH_PATTERN.finditer(text or ""):
        p = (m.group(1) or "").strip()
        if p:
            paths.append(p)

    return paths


def most_probable_file(paths: List[str]) -> Optional[str]:
    if not paths:
        return None

    counts: Dict[str, int] = {}
    for p in paths:
        counts[p] = counts.get(p, 0) + 1

    max_count = max(counts.values())
    candidates = {p for p, c in counts.items() if c == max_count}

    for p in reversed(paths):
        if p in candidates:
            return p

    return next(iter(candidates))


def is_noise_path(path_str: str) -> bool:
    s = (path_str or "").replace("\\", "/").lower()
    return any(
        part in s
        for part in [
            "/.venv/",
            "/venv/",
            "/site-packages/",
            "/dist-packages/",
            "/python3.",
            "/lib/python",
        ]
    )


def safe_resolve_under(root: Path, path_str: str) -> Optional[Path]:
    try:
        root_r = root.resolve()
        p = Path(path_str)
        if not p.is_absolute():
            p = (root / p)
        p_r = p.resolve()
        if not p_r.is_relative_to(root_r):
            return None
        return p_r
    except Exception:
        return None


def read_text_limited(path: Path, *, max_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""

    if max_bytes > 0 and len(data) > max_bytes:
        data = data[:max_bytes] + b"\n\n... (truncated)\n"

    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode(errors="replace")
