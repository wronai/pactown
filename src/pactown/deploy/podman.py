"""Podman deployment backend - rootless containers for production."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from ..config import CacheConfig
from .base import (
    DeploymentBackend,
    DeploymentResult,
    RuntimeType,
)


class PodmanBackend(DeploymentBackend):
    """
    Podman container runtime backend.

    Podman is a daemonless, rootless container engine that is compatible
    with Docker but provides better security for production environments.

    Key advantages:
    - Rootless by default (no root daemon)
    - No daemon = no single point of failure
    - OCI-compliant
    - Systemd integration for service management
    - Pod support (like Kubernetes pods)
    """

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.PODMAN

    def is_available(self) -> bool:
        """Check if Podman is available."""
        try:
            result = subprocess.run(
                ["podman", "version", "--format", "{{.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def build_image(
        self,
        service_name: str,
        dockerfile_path: Path,
        context_path: Path,
        tag: Optional[str] = None,
        build_args: Optional[dict[str, str]] = None,
    ) -> DeploymentResult:
        """Build container image with Podman."""
        image_name = f"{self.config.image_prefix}/{service_name}"
        if tag:
            image_name = f"{image_name}:{tag}"
        else:
            image_name = f"{image_name}:latest"

        cmd = [
            "podman", "build",
            "-t", image_name,
            "-f", str(dockerfile_path),
        ]

        effective_build_args: dict[str, str] = CacheConfig.from_env(os.environ).to_docker_build_args()
        if build_args:
            effective_build_args.update(build_args)

        for key, value in effective_build_args.items():
            if value is None:
                continue
            v = str(value).strip()
            if not v:
                continue
            cmd.extend(["--build-arg", f"{key}={v}"])

        # Add labels
        for key, value in self.config.labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        # Security options for build
        if self.config.rootless:
            cmd.extend(["--userns", "keep-id"])

        cmd.append(str(context_path))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode == 0:
                return DeploymentResult(
                    success=True,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    image_name=image_name,
                )
            else:
                return DeploymentResult(
                    success=False,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    error=result.stderr,
                )
        except subprocess.TimeoutExpired:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error="Build timed out",
            )

    def push_image(
        self,
        image_name: str,
        registry: Optional[str] = None,
    ) -> DeploymentResult:
        """Push image to registry."""
        target = image_name
        if registry:
            target = f"{registry}/{image_name}"
            subprocess.run(
                ["podman", "tag", image_name, target],
                capture_output=True,
            )

        try:
            result = subprocess.run(
                ["podman", "push", target],
                capture_output=True,
                text=True,
                timeout=300,
            )

            return DeploymentResult(
                success=result.returncode == 0,
                service_name=image_name.split("/")[-1].split(":")[0],
                runtime=self.runtime_type,
                image_name=target,
                error=result.stderr if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return DeploymentResult(
                success=False,
                service_name=image_name,
                runtime=self.runtime_type,
                error="Push timed out",
            )

    def deploy(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> DeploymentResult:
        """Deploy a container with Podman."""
        container_name = f"{self.config.namespace}-{service_name}"

        # Stop existing container if running
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            capture_output=True,
        )

        cmd = [
            "podman", "run",
            "-d",
            "--name", container_name,
            "--network", self.config.network_name,
        ]

        # Rootless mode with user namespace
        if self.config.rootless:
            cmd.extend(["--userns", "keep-id"])

        # Port mapping
        if self.config.expose_ports:
            cmd.extend(["-p", f"{port}:{port}"])

        # Environment variables
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Resource limits
        if self.config.memory_limit:
            cmd.extend(["--memory", self.config.memory_limit])
        if self.config.cpu_limit:
            cmd.extend(["--cpus", self.config.cpu_limit])

        # Security options
        if self.config.read_only_fs:
            cmd.append("--read-only")
            cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid"])

        if self.config.no_new_privileges:
            cmd.append("--security-opt=no-new-privileges:true")

        # SELinux context for production
        cmd.extend(["--security-opt", "label=type:container_runtime_t"])

        if self.config.drop_capabilities:
            for cap in self.config.drop_capabilities:
                cmd.extend(["--cap-drop", cap])

        if self.config.add_capabilities:
            for cap in self.config.add_capabilities:
                cmd.extend(["--cap-add", cap])

        # Health check
        if health_check:
            cmd.extend([
                "--health-cmd", f"curl -f http://localhost:{port}{health_check} || exit 1",
                "--health-interval", self.config.health_check_interval,
                "--health-timeout", self.config.health_check_timeout,
                "--health-retries", str(self.config.health_check_retries),
            ])

        # Labels
        for key, value in self.config.labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        # Systemd integration label
        cmd.extend(["--label", "io.containers.autoupdate=registry"])

        cmd.append(image_name)

        try:
            # Ensure network exists
            subprocess.run(
                ["podman", "network", "create", self.config.network_name],
                capture_output=True,
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                container_id = result.stdout.strip()[:12]
                endpoint = f"http://{container_name}:{port}" if self.config.use_internal_dns else f"http://localhost:{port}"

                return DeploymentResult(
                    success=True,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    container_id=container_id,
                    image_name=image_name,
                    endpoint=endpoint,
                )
            else:
                return DeploymentResult(
                    success=False,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    error=result.stderr,
                )
        except subprocess.TimeoutExpired:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error="Deploy timed out",
            )

    def stop(self, service_name: str) -> DeploymentResult:
        """Stop a container."""
        container_name = f"{self.config.namespace}-{service_name}"

        result = subprocess.run(
            ["podman", "stop", container_name],
            capture_output=True,
            text=True,
        )

        subprocess.run(
            ["podman", "rm", container_name],
            capture_output=True,
        )

        return DeploymentResult(
            success=result.returncode == 0,
            service_name=service_name,
            runtime=self.runtime_type,
            error=result.stderr if result.returncode != 0 else None,
        )

    def logs(self, service_name: str, tail: int = 100) -> str:
        """Get container logs."""
        container_name = f"{self.config.namespace}-{service_name}"

        result = subprocess.run(
            ["podman", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
        )

        return result.stdout + result.stderr

    def status(self, service_name: str) -> dict[str, Any]:
        """Get container status."""
        container_name = f"{self.config.namespace}-{service_name}"

        result = subprocess.run(
            ["podman", "inspect", container_name],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {"running": False, "error": "Container not found"}

        try:
            data = json.loads(result.stdout)[0]
            return {
                "running": data["State"]["Running"],
                "status": data["State"]["Status"],
                "health": data["State"].get("Health", {}).get("Status", "unknown"),
                "started_at": data["State"]["StartedAt"],
                "container_id": data["Id"][:12],
                "rootless": True,
            }
        except (json.JSONDecodeError, KeyError, IndexError):
            return {"running": False, "error": "Failed to parse status"}

    def generate_systemd_unit(
        self,
        service_name: str,
        container_name: Optional[str] = None,
    ) -> str:
        """
        Generate systemd unit file for production deployment.

        This allows the container to be managed as a system service
        with automatic restart, logging, and dependency management.
        """
        container_name = container_name or f"{self.config.namespace}-{service_name}"

        return f"""[Unit]
Description=Pactown {service_name} container
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=5
TimeoutStartSec=300
TimeoutStopSec=70

ExecStartPre=-/usr/bin/podman stop {container_name}
ExecStartPre=-/usr/bin/podman rm {container_name}
ExecStart=/usr/bin/podman start -a {container_name}
ExecStop=/usr/bin/podman stop -t 60 {container_name}
ExecStopPost=-/usr/bin/podman rm {container_name}

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

[Install]
WantedBy=multi-user.target
"""

    def create_pod(
        self,
        pod_name: str,
        services: list[str],
        ports: list[int],
    ) -> DeploymentResult:
        """
        Create a Podman pod (similar to Kubernetes pod).

        All containers in a pod share the same network namespace,
        making inter-service communication via localhost possible.
        """
        cmd = [
            "podman", "pod", "create",
            "--name", pod_name,
        ]

        for port in ports:
            cmd.extend(["-p", f"{port}:{port}"])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        return DeploymentResult(
            success=result.returncode == 0,
            service_name=pod_name,
            runtime=self.runtime_type,
            error=result.stderr if result.returncode != 0 else None,
        )
