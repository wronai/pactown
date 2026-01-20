import os
import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


_TRACE_ID_PATTERN = re.compile(
    r"(trace_id|traceid|trace-id|request_id|requestid)[=:\s]+([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)

_PY_TRACE_FILE_PATTERN = re.compile(
    r"File\s+\"([^\"]+)\"\s*,\s*line\s*(\d+)",
    re.IGNORECASE,
)

_GENERIC_PATH_PATTERN = re.compile(r"(/[^\s:\]\)\(\[\{\}<>\"']+\.(?:py|js|ts|tsx|java|go|rs|php|rb))")


@dataclass
class ErrorContextConfig:
    max_log_lines: int = 250
    max_log_chars: int = 12000
    max_stderr_chars: int = 12000
    max_files: int = 6
    max_file_bytes: int = 20000


def _truncate_text(value: str, *, max_chars: int) -> str:
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


def _is_noise_path(path_str: str) -> bool:
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


def _safe_resolve_under(root: Path, path_str: str) -> Optional[Path]:
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


def _read_text_limited(path: Path, *, max_bytes: int) -> str:
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


def build_error_context(
    *,
    sandbox_path: Optional[Path],
    logs: Optional[Iterable[str]] = None,
    stderr: str = "",
    config: Optional[ErrorContextConfig] = None,
    trace_id_override: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = config or ErrorContextConfig()

    logs_list = [str(x) for x in (logs or [])]
    log_tail = logs_list[-cfg.max_log_lines :] if cfg.max_log_lines > 0 else []
    log_text = "\n".join(log_tail)
    log_text = _truncate_text(log_text, max_chars=cfg.max_log_chars)

    stderr_text = _truncate_text(stderr or "", max_chars=cfg.max_stderr_chars)

    combined = "\n".join([stderr_text, log_text])

    trace_ids = extract_trace_ids(combined)

    env_trace_id = (os.environ.get("TRACE_ID") or os.environ.get("PACTOWN_TRACE_ID") or "").strip() or None
    selected_trace_id = trace_id_override or env_trace_id or (trace_ids[-1] if trace_ids else None)

    raw_paths = extract_file_paths(combined)
    preferred_paths = [p for p in raw_paths if not _is_noise_path(p)]
    root_file = most_probable_file(preferred_paths or raw_paths)

    root_file_in_sandbox = None
    root_file_rel = None

    logs_selected: List[str] = []
    if selected_trace_id:
        for line in log_tail:
            if selected_trace_id in line:
                logs_selected.append(line)

    files: List[Dict[str, Any]] = []
    if sandbox_path is not None:
        sb = Path(sandbox_path)
        unique: List[str] = []
        seen = set()
        for p in raw_paths:
            if p in seen:
                continue
            seen.add(p)
            unique.append(p)

        sandbox_candidates: List[str] = []
        for p in raw_paths:
            target = _safe_resolve_under(sb, p)
            if target is None:
                continue
            if not target.exists() or not target.is_file():
                continue
            sandbox_candidates.append(p)
        root_file_in_sandbox = most_probable_file(sandbox_candidates)

        if root_file and root_file in unique:
            unique.remove(root_file)
            unique.insert(0, root_file)
        if root_file_in_sandbox and root_file_in_sandbox in unique:
            unique.remove(root_file_in_sandbox)
            unique.insert(0, root_file_in_sandbox)

        if root_file_in_sandbox:
            try:
                target = _safe_resolve_under(sb, root_file_in_sandbox)
                if target is not None and target.is_relative_to(sb):
                    root_file_rel = str(target.relative_to(sb))
            except Exception:
                root_file_rel = None

        for p in unique:
            if len(files) >= cfg.max_files:
                break
            target = _safe_resolve_under(sb, p)
            if target is None:
                continue
            if not target.exists() or not target.is_file():
                continue
            content = _read_text_limited(target, max_bytes=cfg.max_file_bytes)
            files.append(
                {
                    "path": str(target),
                    "rel": str(target.relative_to(sb)) if target.is_relative_to(sb) else str(target),
                    "size": int(target.stat().st_size) if target.exists() else 0,
                    "content": content,
                }
            )

    return {
        "trace_ids": trace_ids,
        "selected_trace_id": selected_trace_id,
        "root_file": root_file,
        "root_file_in_sandbox": root_file_in_sandbox,
        "root_file_rel": root_file_rel,
        "logs_tail": log_tail,
        "logs_selected": logs_selected,
        "stderr": stderr_text,
        "files": files,
        "sandbox": str(sandbox_path) if sandbox_path else None,
        "pwd": os.getcwd(),
    }


def render_error_report_md(context: Dict[str, Any], *, meta: Optional[Dict[str, Any]] = None) -> str:
    ctx = dict(context or {})
    meta_d = dict(meta or {})

    title = str(meta_d.get("title") or "Error Report")
    generated = datetime.utcnow().isoformat() + "Z"

    message = meta_d.get("message")
    error_category = meta_d.get("error_category")
    port = meta_d.get("port")
    pid = meta_d.get("pid")
    service_id = meta_d.get("service_id")
    service_name = meta_d.get("service_name")

    selected_trace_id = ctx.get("selected_trace_id")
    trace_ids = ctx.get("trace_ids") or []

    root_file = ctx.get("root_file_in_sandbox") or ctx.get("root_file")
    sandbox = ctx.get("sandbox")

    logs_tail = ctx.get("logs_tail") or []
    logs_selected = ctx.get("logs_selected") or []
    stderr_text = ctx.get("stderr") or ""
    files = ctx.get("files") or []

    suggestions = meta_d.get("suggestions") or []
    diagnostics = meta_d.get("diagnostics")

    def fence(body: str, lang: str = "") -> List[str]:
        f = "```"
        header = f + (lang or "")
        return [header, body or "", f]

    def guess_lang(name: str) -> str:
        p = str(name or "").lower()
        if p.endswith(".py"):
            return "python"
        if p.endswith(".js"):
            return "javascript"
        if p.endswith(".ts"):
            return "typescript"
        if p.endswith(".tsx"):
            return "tsx"
        if p.endswith(".json"):
            return "json"
        if p.endswith(".yml") or p.endswith(".yaml"):
            return "yaml"
        if p.endswith(".sh") or p.endswith(".bash"):
            return "bash"
        return ""

    lines: List[str] = [
        f"# {title}",
        f"Generated: {generated}",
        "",
        "## Summary",
    ]

    if message:
        lines.append(f"- **Message:** {message}")
    if error_category:
        lines.append(f"- **Error category:** `{error_category}`")
    if service_id:
        lines.append(f"- **Service ID:** `{service_id}`")
    if service_name:
        lines.append(f"- **Service name:** `{service_name}`")
    if port:
        lines.append(f"- **Port:** `{port}`")
    if pid:
        lines.append(f"- **PID:** `{pid}`")
    lines.append(f"- **Selected trace-id:** `{selected_trace_id or 'N/A'}`")
    lines.append(f"- **Root cause file (heuristic):** `{root_file or 'N/A'}`")
    if sandbox:
        lines.append(f"- **Sandbox:** `{sandbox}`")

    lines.append("")
    lines.append("## Trace IDs found")
    lines.append("")
    if trace_ids:
        lines.append(", ".join([str(x) for x in trace_ids]))
    else:
        lines.append("(none)")

    if selected_trace_id:
        if logs_selected:
            lines.append("")
            lines.append("## Logs (selected trace-id)")
            lines.append("")
            lines.extend(fence("\n".join([str(x) for x in logs_selected]), "text"))

    lines.append("")
    lines.append("## Error output (stderr)")
    lines.append("")
    lines.extend(fence(stderr_text or "(empty)", "text"))

    lines.append("")
    lines.append("## Logs (tail)")
    lines.append("")
    lines.extend(fence("\n".join([str(x) for x in logs_tail]) or "(empty)", "text"))

    if suggestions:
        lines.append("")
        lines.append("## Suggestions")
        lines.append("")
        for s in suggestions:
            if isinstance(s, dict):
                desc = s.get("description") or s.get("action") or "(suggestion)"
                cmd = s.get("command")
                if cmd:
                    lines.append(f"- {desc} (`{cmd}`)")
                else:
                    lines.append(f"- {desc}")
            else:
                lines.append(f"- {s}")

    if diagnostics:
        lines.append("")
        lines.append("## Diagnostics")
        lines.append("")
        if isinstance(diagnostics, dict):
            for k, v in diagnostics.items():
                lines.append(f"- **{k}:** `{v}`")
        else:
            lines.append(str(diagnostics))

    lines.append("")
    lines.append("## Files referenced")
    lines.append("")
    if not files:
        lines.append("(no sandbox files found in stack traces)")
    else:
        for f in files:
            rel = f.get("rel") or f.get("path") or "(file)"
            content = f.get("content") or ""
            lines.append(f"### `{rel}`")
            lines.append("")
            lines.extend(fence(content or "(empty)", guess_lang(str(rel))))
            lines.append("")

    return "\n".join(lines)
