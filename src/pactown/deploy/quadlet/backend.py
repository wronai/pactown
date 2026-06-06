"""Quadlet deployment backend."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from ...config import CacheConfig
from ..base import DeploymentBackend, DeploymentConfig, DeploymentResult, RuntimeType
from .config import QuadletConfig, QuadletUnit
from .sanitize import check_dangerous_content, sanitize_name, validate_volume
from .templates import QuadletTemplates

try:
    from ...nfo_config import logged
except Exception:
    def logged(cls=None, **kw):
        return cls if cls is not None else lambda c: c


@logged
class QuadletBackend(DeploymentBackend):
    """
    Podman Quadlet deployment backend.

    Generates systemd-native unit files for container management,
    providing a lightweight alternative to Kubernetes.
    """

    def __init__(self, config: DeploymentConfig, quadlet_config: QuadletConfig = None):
        super().__init__(config)
        self.quadlet = quadlet_config or QuadletConfig()

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.PODMAN

    def is_available(self) -> bool:
        """Check if Podman with Quadlet support is available."""
        try:
            # Check podman
            result = subprocess.run(
                ["podman", "version", "--format", "{{.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False

            # Check for Quadlet (available in Podman 4.4+)
            version = result.stdout.strip()
            major, minor = map(int, version.split(".")[:2])
            return major > 4 or (major == 4 and minor >= 4)
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return False

    def get_quadlet_version(self) -> Optional[str]:
        """Get Quadlet/Podman version."""
        try:
            result = subprocess.run(
                ["podman", "version", "--format", "{{.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

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

        effective_build_args: dict[str, str] = CacheConfig.from_env().to_docker_build_args()
        if build_args:
            effective_build_args.update(build_args)

        for key, value in effective_build_args.items():
            if value is None:
                continue
            v = str(value).strip()
            if not v:
                continue
            cmd.extend(["--build-arg", f"{key}={v}"])

        cmd.append(str(context_path))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            return DeploymentResult(
                success=result.returncode == 0,
                service_name=service_name,
                runtime=self.runtime_type,
                image_name=image_name,
                error=result.stderr if result.returncode != 0 else None,
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
        target = f"{registry}/{image_name}" if registry else image_name

        try:
            if registry:
                subprocess.run(
                    ["podman", "tag", image_name, target],
                    capture_output=True,
                )

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

    def generate_quadlet_files(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str] = None,
        health_check: Optional[str] = None,
        volumes: list[str] = None,
        depends_on: list[str] = None,
    ) -> list[QuadletUnit]:
        """Generate Quadlet unit files for a service."""
        units = []

        # Container unit
        container = QuadletTemplates.container(
            name=service_name,
            image=image_name,
            port=port,
            config=self.quadlet,
            env=env,
            health_check=health_check,
            volumes=volumes,
            depends_on=depends_on,
        )
        units.append(container)

        return units

    def deploy(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> DeploymentResult:
        """Deploy a service using Quadlet."""
        try:
            # Generate Quadlet files
            units = self.generate_quadlet_files(
                service_name=service_name,
                image_name=image_name,
                port=port,
                env=env,
                health_check=health_check,
            )

            # Save to tenant directory
            tenant_path = self.quadlet.tenant_path
            for unit in units:
                unit.save(tenant_path)

            # Reload systemd daemon
            self._systemctl("daemon-reload")

            # Start the service
            service = f"{service_name}.service"
            self._systemctl("start", service)
            self._systemctl("enable", service)

            endpoint = f"https://{self.quadlet.full_domain}" if self.quadlet.tls_enabled else f"http://{self.quadlet.full_domain}"

            return DeploymentResult(
                success=True,
                service_name=service_name,
                runtime=self.runtime_type,
                image_name=image_name,
                endpoint=endpoint,
            )
        except Exception as e:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error=str(e),
            )

    def stop(self, service_name: str) -> DeploymentResult:
        """Stop a Quadlet service."""
        try:
            service = f"{service_name}.service"
            self._systemctl("stop", service)
            self._systemctl("disable", service)

            # Remove unit files
            tenant_path = self.quadlet.tenant_path
            for ext in ["container", "pod", "network", "volume"]:
                unit_file = tenant_path / f"{service_name}.{ext}"
                if unit_file.exists():
                    unit_file.unlink()

            self._systemctl("daemon-reload")

            return DeploymentResult(
                success=True,
                service_name=service_name,
                runtime=self.runtime_type,
            )
        except Exception as e:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error=str(e),
            )

    def logs(self, service_name: str, tail: int = 100) -> str:
        """Get service logs via journalctl."""
        try:
            cmd = ["journalctl"]
            if self.quadlet.user_mode:
                cmd.append("--user")
            cmd.extend(["-u", f"{service_name}.service", "-n", str(tail), "--no-pager"])

            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout
        except Exception:
            return ""

    def status(self, service_name: str) -> dict[str, Any]:
        """Get service status."""
        try:
            cmd = ["systemctl"]
            if self.quadlet.user_mode:
                cmd.append("--user")
            cmd.extend(["show", f"{service_name}.service", "--property=ActiveState,SubState,MainPID"])

            result = subprocess.run(cmd, capture_output=True, text=True)

            status = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    status[key] = value

            return {
                "running": status.get("ActiveState") == "active",
                "state": status.get("SubState", "unknown"),
                "pid": status.get("MainPID", "0"),
                "quadlet": True,
                "tenant": self.quadlet.tenant_id,
            }
        except Exception:
            return {"running": False, "error": "Failed to get status"}

    def _systemctl(self, command: str, service: str = None) -> subprocess.CompletedProcess:
        """Run systemctl command."""
        cmd = ["systemctl"]
        if self.quadlet.user_mode:
            cmd.append("--user")
        cmd.append(command)
        if service:
            cmd.append(service)

        return subprocess.run(cmd, capture_output=True, text=True)

    def list_services(self) -> list[dict[str, Any]]:
        """List all Quadlet services for the tenant."""
        services = []
        tenant_path = self.quadlet.tenant_path

        if tenant_path.exists():
            for f in tenant_path.glob("*.container"):
                name = f.stem
                status = self.status(name)
                services.append({
                    "name": name,
                    "status": status,
                    "unit_file": str(f),
                })

        return services


