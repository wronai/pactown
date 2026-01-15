"""Podman Quadlet deployment backend - systemd-native container management.

Quadlet generates systemd unit files from simple .container/.pod/.network files,
providing a lightweight alternative to Kubernetes for single-node VPS deployments.

Key benefits:
- Zero daemon overhead (unlike kubelet)
- Native systemd integration (auto-restart, logging, dependencies)
- Rootless containers by default
- Simple file-based configuration in ~/.config/containers/systemd/
- Perfect for MVP deployments on single VPS (e.g., Hetzner CX53)
"""

from __future__ import annotations

import os
import subprocess
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from string import Template

from .base import (
    DeploymentBackend,
    DeploymentConfig,
    DeploymentResult,
    RuntimeType,
    DeploymentMode,
)


@dataclass
class QuadletConfig:
    """Configuration for Quadlet deployment."""
    
    # Tenant/user identification
    tenant_id: str = "default"
    
    # Domain configuration
    domain: str = "localhost"
    subdomain: Optional[str] = None
    tls_enabled: bool = False
    
    # Traefik labels for routing
    traefik_enabled: bool = True
    traefik_entrypoint: str = "websecure"
    traefik_certresolver: str = "letsencrypt"
    
    # Resource limits
    cpus: str = "0.5"
    memory: str = "256M"
    memory_max: str = "512M"
    
    # Networking
    network_mode: str = "bridge"  # bridge, host, slirp4netns
    publish_ports: bool = True
    
    # Auto-update
    auto_update: str = "registry"  # registry, local, or empty
    
    # Systemd user mode
    user_mode: bool = True  # Use ~/.config/containers/systemd/ vs /etc/containers/systemd/
    
    @property
    def full_domain(self) -> str:
        """Get full domain with subdomain."""
        if self.subdomain:
            return f"{self.subdomain}.{self.domain}"
        return self.domain
    
    @property
    def systemd_path(self) -> Path:
        """Get systemd unit files path."""
        if self.user_mode:
            return Path.home() / ".config" / "containers" / "systemd"
        return Path("/etc/containers/systemd")
    
    @property
    def tenant_path(self) -> Path:
        """Get tenant-specific directory."""
        return self.systemd_path / f"tenant-{self.tenant_id}"


@dataclass
class QuadletUnit:
    """Represents a Quadlet unit file."""
    name: str
    unit_type: str  # container, pod, network, volume, kube
    content: str
    
    @property
    def filename(self) -> str:
        return f"{self.name}.{self.unit_type}"
    
    def save(self, directory: Path) -> Path:
        """Save unit file to directory."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(self.content)
        return path


class QuadletTemplates:
    """Template generator for Quadlet unit files."""
    
    CONTAINER_TEMPLATE = Template("""[Unit]
Description=${description}
After=network-online.target
Wants=network-online.target
${after_units}

[Container]
ContainerName=${container_name}
Image=${image}
${environment}
${publish_ports}
${volumes}
${labels}

# Resource limits
PodmanArgs=--cpus=${cpus} --memory=${memory} --memory-reservation=${memory_max}

# Security
PodmanArgs=--security-opt=no-new-privileges:true
${rootless_args}

# Health check
${health_check}

# Auto-update
AutoUpdate=${auto_update}

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=300
TimeoutStopSec=70

[Install]
WantedBy=default.target
""")

    POD_TEMPLATE = Template("""[Unit]
Description=${description}
After=network-online.target
Wants=network-online.target

[Pod]
PodName=${pod_name}
${publish_ports}
Network=${network}

[Install]
WantedBy=default.target
""")

    NETWORK_TEMPLATE = Template("""[Unit]
Description=${description}

[Network]
NetworkName=${network_name}
Driver=${driver}
${subnet}
${gateway}
${labels}

[Install]
WantedBy=default.target
""")

    VOLUME_TEMPLATE = Template("""[Unit]
Description=${description}

[Volume]
VolumeName=${volume_name}
${labels}

[Install]
WantedBy=default.target
""")

    KUBE_TEMPLATE = Template("""[Unit]
Description=${description}
After=network-online.target
Wants=network-online.target

[Kube]
Yaml=${yaml_path}
${publish_ports}
Network=${network}
${config_maps}

[Install]
WantedBy=default.target
""")

    @classmethod
    def container(
        cls,
        name: str,
        image: str,
        port: int,
        config: QuadletConfig,
        env: dict[str, str] = None,
        health_check: Optional[str] = None,
        volumes: list[str] = None,
        depends_on: list[str] = None,
    ) -> QuadletUnit:
        """Generate .container unit file."""
        env = env or {}
        volumes = volumes or []
        depends_on = depends_on or []
        
        # Build environment lines
        env_lines = []
        for key, value in env.items():
            env_lines.append(f"Environment={key}={value}")
        
        # Add Traefik labels if enabled
        labels = []
        if config.traefik_enabled:
            labels.extend([
                f"Label=traefik.enable=true",
                f"Label=traefik.http.routers.{name}.rule=Host(`{config.full_domain}`)",
                f"Label=traefik.http.routers.{name}.entrypoints={config.traefik_entrypoint}",
                f"Label=traefik.http.services.{name}.loadbalancer.server.port={port}",
            ])
            if config.tls_enabled:
                labels.extend([
                    f"Label=traefik.http.routers.{name}.tls=true",
                    f"Label=traefik.http.routers.{name}.tls.certresolver={config.traefik_certresolver}",
                ])
        
        # Publish ports
        publish = ""
        if config.publish_ports:
            publish = f"PublishPort={port}:{port}"
        
        # Volumes
        vol_lines = [f"Volume={v}" for v in volumes]
        
        # Dependencies
        after_lines = []
        for dep in depends_on:
            after_lines.append(f"After={dep}.service")
        
        # Health check
        hc = ""
        if health_check:
            hc = f"HealthCmd=curl -sf http://localhost:{port}{health_check} || exit 1\nHealthInterval=30s\nHealthTimeout=10s\nHealthRetries=3"
        
        # Rootless args
        rootless = "PodmanArgs=--userns=keep-id" if config.user_mode else ""
        
        content = cls.CONTAINER_TEMPLATE.substitute(
            description=f"Pactown service: {name} (tenant: {config.tenant_id})",
            container_name=f"{config.tenant_id}-{name}",
            image=image,
            environment="\n".join(env_lines) if env_lines else "# No environment variables",
            publish_ports=publish,
            volumes="\n".join(vol_lines) if vol_lines else "# No volumes",
            labels="\n".join(labels) if labels else "# No labels",
            cpus=config.cpus,
            memory=config.memory,
            memory_max=config.memory_max,
            rootless_args=rootless,
            health_check=hc if hc else "# No health check",
            auto_update=config.auto_update,
            after_units="\n".join(after_lines) if after_lines else "",
        )
        
        return QuadletUnit(name=name, unit_type="container", content=content)

    @classmethod
    def pod(
        cls,
        name: str,
        config: QuadletConfig,
        ports: list[int] = None,
        network: str = "pactown-net",
    ) -> QuadletUnit:
        """Generate .pod unit file."""
        ports = ports or []
        
        publish = "\n".join([f"PublishPort={p}:{p}" for p in ports]) if ports else ""
        
        content = cls.POD_TEMPLATE.substitute(
            description=f"Pactown pod: {name} (tenant: {config.tenant_id})",
            pod_name=f"{config.tenant_id}-{name}",
            publish_ports=publish,
            network=network,
        )
        
        return QuadletUnit(name=name, unit_type="pod", content=content)

    @classmethod
    def network(
        cls,
        name: str,
        config: QuadletConfig,
        driver: str = "bridge",
        subnet: Optional[str] = None,
        gateway: Optional[str] = None,
    ) -> QuadletUnit:
        """Generate .network unit file."""
        content = cls.NETWORK_TEMPLATE.substitute(
            description=f"Pactown network: {name}",
            network_name=name,
            driver=driver,
            subnet=f"Subnet={subnet}" if subnet else "",
            gateway=f"Gateway={gateway}" if gateway else "",
            labels=f"Label=pactown.tenant={config.tenant_id}",
        )
        
        return QuadletUnit(name=name, unit_type="network", content=content)

    @classmethod
    def volume(
        cls,
        name: str,
        config: QuadletConfig,
    ) -> QuadletUnit:
        """Generate .volume unit file."""
        content = cls.VOLUME_TEMPLATE.substitute(
            description=f"Pactown volume: {name}",
            volume_name=f"{config.tenant_id}-{name}",
            labels=f"Label=pactown.tenant={config.tenant_id}",
        )
        
        return QuadletUnit(name=name, unit_type="volume", content=content)


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
        except:
            return None
    
    def build_image(
        self,
        service_name: str,
        dockerfile_path: Path,
        context_path: Path,
        tag: Optional[str] = None,
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
            str(context_path),
        ]
        
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
        except:
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
        except:
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


def generate_traefik_quadlet(config: QuadletConfig) -> list[QuadletUnit]:
    """Generate Traefik reverse proxy Quadlet files."""
    units = []
    
    # Traefik container
    traefik_content = f"""[Unit]
Description=Traefik Reverse Proxy
After=network-online.target
Wants=network-online.target

[Container]
ContainerName=traefik
Image=docker.io/traefik:v3.0

# Entrypoints
Environment=TRAEFIK_ENTRYPOINTS_WEB_ADDRESS=:80
Environment=TRAEFIK_ENTRYPOINTS_WEBSECURE_ADDRESS=:443
Environment=TRAEFIK_PROVIDERS_DOCKER=true
Environment=TRAEFIK_PROVIDERS_DOCKER_EXPOSEDBYDEFAULT=false

# Let's Encrypt
Environment=TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_EMAIL=admin@{config.domain}
Environment=TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_STORAGE=/letsencrypt/acme.json
Environment=TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_HTTPCHALLENGE_ENTRYPOINT=web

# API dashboard
Environment=TRAEFIK_API_DASHBOARD=true
Environment=TRAEFIK_API_INSECURE=false

PublishPort=80:80
PublishPort=443:443

Volume=/run/podman/podman.sock:/var/run/docker.sock:ro
Volume=traefik-letsencrypt:/letsencrypt

# Security
PodmanArgs=--security-opt=no-new-privileges:true

AutoUpdate=registry

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    
    units.append(QuadletUnit(name="traefik", unit_type="container", content=traefik_content))
    
    # Traefik volume for Let's Encrypt
    volume_content = f"""[Unit]
Description=Traefik Let's Encrypt storage

[Volume]
VolumeName=traefik-letsencrypt

[Install]
WantedBy=default.target
"""
    
    units.append(QuadletUnit(name="traefik-letsencrypt", unit_type="volume", content=volume_content))
    
    return units


def generate_markdown_service_quadlet(
    markdown_path: Path,
    config: QuadletConfig,
    image: str = "ghcr.io/pactown/markdown-server:latest",
) -> list[QuadletUnit]:
    """
    Generate Quadlet files for serving a Markdown file.
    
    This creates a simple container that serves the Markdown as a web page
    with live reload and syntax highlighting.
    """
    name = markdown_path.stem.lower().replace(" ", "-").replace("_", "-")
    
    container_content = f"""[Unit]
Description=Markdown Service: {markdown_path.name}
After=network-online.target traefik.service
Wants=network-online.target

[Container]
ContainerName={config.tenant_id}-{name}
Image={image}

# Mount the Markdown file
Volume={markdown_path}:/app/content/README.md:ro

# Environment
Environment=MARKDOWN_TITLE={markdown_path.stem}
Environment=MARKDOWN_THEME=github
Environment=PORT=8080

# Traefik labels
Label=traefik.enable=true
Label=traefik.http.routers.{name}.rule=Host(`{config.full_domain}`)
Label=traefik.http.routers.{name}.entrypoints={config.traefik_entrypoint}
Label=traefik.http.services.{name}.loadbalancer.server.port=8080
{"Label=traefik.http.routers." + name + ".tls=true" if config.tls_enabled else ""}
{"Label=traefik.http.routers." + name + ".tls.certresolver=" + config.traefik_certresolver if config.tls_enabled else ""}

# Resource limits
PodmanArgs=--cpus={config.cpus} --memory={config.memory}

# Security
PodmanArgs=--security-opt=no-new-privileges:true
PodmanArgs=--read-only
PodmanArgs=--tmpfs=/tmp:rw,noexec,nosuid

AutoUpdate=registry

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    
    return [QuadletUnit(name=name, unit_type="container", content=container_content)]
