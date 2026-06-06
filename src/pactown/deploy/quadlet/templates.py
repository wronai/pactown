"""Quadlet systemd unit templates."""
from __future__ import annotations

from string import Template
from typing import Any, Optional

from ..base import DeploymentConfig, RuntimeType
from .config import QuadletConfig, QuadletUnit
from .sanitize import (
    sanitize_domain,
    sanitize_env_key,
    sanitize_env_value,
    sanitize_health_check,
    sanitize_image,
    sanitize_name,
    sanitize_path,
    validate_volume,
)

try:
    from ...nfo_config import logged
except Exception:
    def logged(cls=None, **kw):
        return cls if cls is not None else lambda c: c

@logged
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
        """Generate .container unit file with security sanitization."""
        env = env or {}
        volumes = volumes or []
        depends_on = depends_on or []

        # === SECURITY: Sanitize all inputs ===
        safe_name = sanitize_name(name)
        safe_image = sanitize_image(image)
        safe_tenant = sanitize_name(config.tenant_id)
        safe_domain = sanitize_domain(config.full_domain)

        # Build environment lines with sanitization
        env_lines = []
        for key, value in env.items():
            safe_key = sanitize_env_key(key)
            safe_value = sanitize_env_value(str(value))
            env_lines.append(f"Environment={safe_key}={safe_value}")

        # Add Traefik labels if enabled (with sanitized values)
        labels = []
        if config.traefik_enabled:
            labels.extend([
                "Label=traefik.enable=true",
                f"Label=traefik.http.routers.{safe_name}.rule=Host(`{safe_domain}`)",
                f"Label=traefik.http.routers.{safe_name}.entrypoints={config.traefik_entrypoint}",
                f"Label=traefik.http.services.{safe_name}.loadbalancer.server.port={port}",
            ])
            if config.tls_enabled:
                labels.extend([
                    f"Label=traefik.http.routers.{safe_name}.tls=true",
                    f"Label=traefik.http.routers.{safe_name}.tls.certresolver={config.traefik_certresolver}",
                ])

        # Publish ports
        publish = ""
        if config.publish_ports:
            publish = f"PublishPort={port}:{port}"

        # Volumes with validation
        vol_lines = []
        for v in volumes:
            is_valid, result = validate_volume(v)
            if is_valid:
                vol_lines.append(f"Volume={result}")
            # Skip invalid/dangerous volumes silently

        # Dependencies (sanitized)
        after_lines = []
        for dep in depends_on:
            safe_dep = sanitize_name(dep)
            after_lines.append(f"After={safe_dep}.service")

        # Health check (sanitized)
        hc = ""
        if health_check:
            safe_hc = sanitize_health_check(health_check)
            hc = (f"HealthCmd=curl -sf http://localhost:{port}{safe_hc} || exit 1\n"
                  "HealthInterval=30s\nHealthTimeout=10s\nHealthRetries=3")

        # Rootless args
        rootless = "PodmanArgs=--userns=keep-id" if config.user_mode else ""

        content = cls.CONTAINER_TEMPLATE.substitute(
            description=f"Pactown service: {safe_name} (tenant: {safe_tenant})",
            container_name=f"{safe_tenant}-{safe_name}",
            image=safe_image,
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

        return QuadletUnit(name=safe_name, unit_type="container", content=content)

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
