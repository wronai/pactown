import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..iac.validate import infer_failure_phase, load_sandbox_manifest
from .extractors import (
    extract_file_paths,
    extract_trace_ids,
    is_noise_path,
    most_probable_file,
    read_text_limited,
    safe_resolve_under,
    truncate_text,
)
from .types import ErrorContextConfig


def _load_manifest(sandbox_path: Optional[Path]) -> Optional[dict[str, Any]]:
    if sandbox_path is None:
        return None
    manifest_path = sandbox_path / "pactown.sandbox.yaml"
    if not manifest_path.exists():
        return None
    try:
        return load_sandbox_manifest(manifest_path)
    except Exception:
        return None


def _collect_sandbox_files(
    *,
    sandbox_path: Path,
    raw_paths: List[str],
    root_file: Optional[str],
    root_file_in_sandbox: Optional[str],
    cfg: ErrorContextConfig,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    files: List[Dict[str, Any]] = []
    root_file_rel: Optional[str] = None

    unique: List[str] = []
    seen = set()
    for p in raw_paths:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)

    if root_file and root_file in unique:
        unique.remove(root_file)
        unique.insert(0, root_file)
    if root_file_in_sandbox and root_file_in_sandbox in unique:
        unique.remove(root_file_in_sandbox)
        unique.insert(0, root_file_in_sandbox)

    if root_file_in_sandbox:
        try:
            target = safe_resolve_under(sandbox_path, root_file_in_sandbox)
            if target is not None and target.is_relative_to(sandbox_path):
                root_file_rel = str(target.relative_to(sandbox_path))
        except Exception:
            root_file_rel = None

    for p in unique:
        if len(files) >= cfg.max_files:
            break
        target = safe_resolve_under(sandbox_path, p)
        if target is None:
            continue
        if not target.exists() or not target.is_file():
            continue
        content = read_text_limited(target, max_bytes=cfg.max_file_bytes)
        files.append(
            {
                "path": str(target),
                "rel": str(target.relative_to(sandbox_path)) if target.is_relative_to(sandbox_path) else str(target),
                "size": int(target.stat().st_size) if target.exists() else 0,
                "content": content,
            }
        )

    return files, root_file_rel


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
    log_text = truncate_text(log_text, max_chars=cfg.max_log_chars)

    stderr_text = truncate_text(stderr or "", max_chars=cfg.max_stderr_chars)
    combined = "\n".join([stderr_text, log_text])

    trace_ids = extract_trace_ids(combined)
    env_trace_id = (os.environ.get("TRACE_ID") or os.environ.get("PACTOWN_TRACE_ID") or "").strip() or None
    selected_trace_id = trace_id_override or env_trace_id or (trace_ids[-1] if trace_ids else None)

    raw_paths = extract_file_paths(combined)
    preferred_paths = [p for p in raw_paths if not is_noise_path(p)]
    root_file = most_probable_file(preferred_paths or raw_paths)

    manifest = _load_manifest(sandbox_path)
    failure_phase = infer_failure_phase(stderr=stderr_text, logs=log_tail, manifest=manifest)

    logs_selected: List[str] = []
    if selected_trace_id:
        for line in log_tail:
            if selected_trace_id in line:
                logs_selected.append(line)

    root_file_in_sandbox = None
    files: List[Dict[str, Any]] = []
    root_file_rel = None

    if sandbox_path is not None:
        sb = Path(sandbox_path)
        sandbox_candidates: List[str] = []
        for p in raw_paths:
            target = safe_resolve_under(sb, p)
            if target is None:
                continue
            if not target.exists() or not target.is_file():
                continue
            sandbox_candidates.append(p)
        root_file_in_sandbox = most_probable_file(sandbox_candidates)
        files, root_file_rel = _collect_sandbox_files(
            sandbox_path=sb,
            raw_paths=raw_paths,
            root_file=root_file,
            root_file_in_sandbox=root_file_in_sandbox,
            cfg=cfg,
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
        "failure_phase": failure_phase,
        "iac_manifest": manifest.get("metadata", {}).get("name") if manifest else None,
    }
