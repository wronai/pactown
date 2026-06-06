"""Quadlet configuration dataclasses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .sanitize import sanitize_domain, sanitize_name

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
        """Get full domain with subdomain (sanitized)."""
        safe_domain = sanitize_domain(self.domain)
        if self.subdomain:
            safe_subdomain = sanitize_domain(self.subdomain)
            return f"{safe_subdomain}.{safe_domain}"
        return safe_domain

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
        # Sanitize filename to prevent injection
        safe_name = sanitize_name(self.name)
        safe_type = re.sub(r'[^a-zA-Z0-9]', '', self.unit_type)
        return f"{safe_name}.{safe_type}"

    def save(self, directory: Path) -> Path:
        """Save unit file to directory."""
        directory.mkdir(parents=True, exist_ok=True)
        # Use sanitized filename
        path = directory / self.filename
        path.write_text(self.content)
        return path

