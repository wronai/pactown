from __future__ import annotations

from pathlib import Path

from .runtime import SandboxRuntime, default_base_image, resolve_oci_image
from .workload import WorkloadConfig


def write_runtime_dockerfile(
    *,
    sandbox_path: Path,
    run_cmd: str,
    runtime: SandboxRuntime | str,
    workload: WorkloadConfig | None = None,
    is_node: bool = False,
) -> Path:
    r = runtime if isinstance(runtime, SandboxRuntime) else SandboxRuntime(runtime)
    out = sandbox_path / "Dockerfile"
    cmd = (run_cmd or "").strip() or "true"

    if r == SandboxRuntime.OCI_IMAGE:
        image = resolve_oci_image(run_cmd=run_cmd, workload=workload) or default_base_image(runtime=r)
        content = _oci_image_dockerfile(image=image, run_cmd=cmd, workload=workload)
    elif r == SandboxRuntime.SHELL:
        base = default_base_image(runtime=r)
        content = _shell_dockerfile(base_image=base, run_cmd=cmd)
    elif r == SandboxRuntime.GO:
        base = default_base_image(runtime=r)
        content = _go_dockerfile(base_image=base, run_cmd=cmd)
    else:
        from ..deploy.docker import DockerBackend
        from ..deploy.base import DeploymentConfig

        backend = DockerBackend(DeploymentConfig.for_development())
        backend.generate_dockerfile(
            service_name=sandbox_path.name,
            sandbox_path=sandbox_path,
            base_image=default_base_image(runtime=r, is_node=is_node),
            run_cmd=cmd,
        )
        return out

    out.write_text(content)
    return out


def _shell_dockerfile(*, base_image: str, run_cmd: str) -> str:
    escaped = run_cmd.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join(
        [
            f"FROM {base_image}",
            "",
            "WORKDIR /app",
            "RUN useradd -m -u 1000 appuser",
            "",
            "COPY . .",
            "RUN chown -R appuser:appuser /app",
            "USER appuser",
            "",
            f'CMD ["/bin/bash", "-lc", "{escaped}"]',
            "",
        ]
    )


def _go_dockerfile(*, base_image: str, run_cmd: str) -> str:
    escaped = run_cmd.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join(
        [
            f"FROM {base_image}",
            "",
            "WORKDIR /app",
            "RUN apk add --no-cache git",
            "",
            "COPY go.mod go.sum* ./",
            "RUN go mod download 2>/dev/null || true",
            "",
            "COPY . .",
            "RUN go mod tidy 2>/dev/null || true",
            "",
            f'CMD ["/bin/sh", "-c", "{escaped}"]',
            "",
        ]
    )


def _oci_image_dockerfile(*, image: str, run_cmd: str, workload: WorkloadConfig | None) -> str:
    lines = [f"FROM {image}", "", "WORKDIR /app", ""]

    has_local_files = workload is None or workload.entrypoint is None
    if has_local_files:
        lines.extend(
            [
                "COPY . .",
                "",
            ]
        )

    if workload and workload.entrypoint:
        entry = workload.entrypoint.replace('"', '\\"')
        if workload.args:
            import json

            args_json = json.dumps([str(a) for a in workload.args])
            lines.append(f'ENTRYPOINT ["{entry}"]')
            lines.append(f"CMD {args_json}")
        else:
            lines.append(f'ENTRYPOINT ["{entry}"]')
    else:
        escaped = run_cmd.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'CMD ["/bin/sh", "-c", "{escaped}"]')

    lines.append("")
    return "\n".join(lines)
