"""High-level Quadlet unit generators."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .backend import QuadletBackend
from .config import QuadletConfig, QuadletUnit
from .sanitize import sanitize_domain, sanitize_name
from .templates import QuadletTemplates

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
    volume_content = """[Unit]
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
{f"Label=traefik.http.routers.{name}.tls=true" if config.tls_enabled else ""}
{f"Label=traefik.http.routers.{name}.tls.certresolver={config.traefik_certresolver}" if config.tls_enabled else ""}

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
