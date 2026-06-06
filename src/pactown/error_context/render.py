from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _fence(body: str, lang: str = "") -> List[str]:
    header = "```" + (lang or "")
    return [header, body or "", "```"]


def _guess_lang(name: str) -> str:
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


def _append_summary(lines: List[str], *, meta_d: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    message = meta_d.get("message")
    error_category = meta_d.get("error_category")
    port = meta_d.get("port")
    pid = meta_d.get("pid")
    service_id = meta_d.get("service_id")
    service_name = meta_d.get("service_name")
    selected_trace_id = ctx.get("selected_trace_id")
    root_file = ctx.get("root_file_in_sandbox") or ctx.get("root_file")
    sandbox = ctx.get("sandbox")
    failure_phase = ctx.get("failure_phase")

    if message:
        lines.append(f"- **Message:** {message}")
    if error_category:
        lines.append(f"- **Error category:** `{error_category}`")
    if failure_phase:
        lines.append(f"- **Failure phase (IaC):** `{failure_phase}`")
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


def render_error_report_md(context: Dict[str, Any], *, meta: Optional[Dict[str, Any]] = None) -> str:
    ctx = dict(context or {})
    meta_d = dict(meta or {})

    title = str(meta_d.get("title") or "Error Report")
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    trace_ids = ctx.get("trace_ids") or []
    logs_tail = ctx.get("logs_tail") or []
    logs_selected = ctx.get("logs_selected") or []
    stderr_text = ctx.get("stderr") or ""
    files = ctx.get("files") or []
    selected_trace_id = ctx.get("selected_trace_id")
    suggestions = meta_d.get("suggestions") or []
    diagnostics = meta_d.get("diagnostics")

    lines: List[str] = [
        f"# {title}",
        f"Generated: {generated}",
        "",
        "## Summary",
    ]
    _append_summary(lines, meta_d=meta_d, ctx=ctx)

    lines.append("")
    lines.append("## Trace IDs found")
    lines.append("")
    if trace_ids:
        lines.append(", ".join([str(x) for x in trace_ids]))
    else:
        lines.append("(none)")

    if selected_trace_id and logs_selected:
        lines.append("")
        lines.append("## Logs (selected trace-id)")
        lines.append("")
        lines.extend(_fence("\n".join([str(x) for x in logs_selected]), "text"))

    lines.append("")
    lines.append("## Error output (stderr)")
    lines.append("")
    lines.extend(_fence(stderr_text or "(empty)", "text"))

    lines.append("")
    lines.append("## Logs (tail)")
    lines.append("")
    lines.extend(_fence("\n".join([str(x) for x in logs_tail]) or "(empty)", "text"))

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
            lines.extend(_fence(content or "(empty)", _guess_lang(str(rel))))
            lines.append("")

    return "\n".join(lines)
