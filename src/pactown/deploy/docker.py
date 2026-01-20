"""Docker deployment backend."""

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


class DockerBackend(DeploymentBackend):
    """Docker container runtime backend."""

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.DOCKER

    def is_available(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
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
        """Build Docker image."""
        image_name = f"{self.config.image_prefix}/{service_name}"
        if tag:
            image_name = f"{image_name}:{tag}"
        else:
            image_name = f"{image_name}:latest"

        cmd = [
            "docker", "build",
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
            # Tag for registry
            subprocess.run(
                ["docker", "tag", image_name, target],
                capture_output=True,
            )

        try:
            result = subprocess.run(
                ["docker", "push", target],
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
        """Deploy a container."""
        container_name = f"{self.config.namespace}-{service_name}"

        # Stop existing container if running
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
        )

        cmd = [
            "docker", "run",
            "-d",
            "--name", container_name,
            "--network", self.config.network_name,
            "--restart", "unless-stopped",
        ]

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
            cmd.extend(["--tmpfs", "/tmp"])

        if self.config.no_new_privileges:
            cmd.append("--security-opt=no-new-privileges:true")

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

        cmd.append(image_name)

        try:
            # Ensure network exists
            subprocess.run(
                ["docker", "network", "create", self.config.network_name],
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
            ["docker", "stop", container_name],
            capture_output=True,
            text=True,
        )

        subprocess.run(
            ["docker", "rm", container_name],
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
            ["docker", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
        )

        return result.stdout + result.stderr

    def status(self, service_name: str) -> dict[str, Any]:
        """Get container status."""
        container_name = f"{self.config.namespace}-{service_name}"

        result = subprocess.run(
            ["docker", "inspect", container_name],
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
            }
        except (json.JSONDecodeError, KeyError, IndexError):
            return {"running": False, "error": "Failed to parse status"}
