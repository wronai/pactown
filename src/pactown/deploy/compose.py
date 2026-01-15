"""Docker Compose / Podman Compose generator for multi-service deployment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from ..config import EcosystemConfig, ServiceConfig
from .base import DeploymentConfig, DeploymentMode


@dataclass
class ComposeService:
    """Represents a service in docker-compose.yaml."""
    name: str
    build_context: str
    dockerfile: str
    image: str
    ports: list[str]
    environment: dict[str, str]
    depends_on: list[str]
    health_check: Optional[dict] = None
    deploy: Optional[dict] = None
    networks: list[str] = None
    volumes: list[str] = None


class ComposeGenerator:
    """
    Generate Docker Compose / Podman Compose files for pactown ecosystems.

    Supports:
    - Docker Compose v3.8+
    - Podman Compose
    - Docker Swarm mode
    """

    def __init__(
        self,
        ecosystem: EcosystemConfig,
        deploy_config: DeploymentConfig,
        base_path: Path,
    ):
        self.ecosystem = ecosystem
        self.deploy_config = deploy_config
        self.base_path = Path(base_path)

    def generate(
        self,
        output_path: Optional[Path] = None,
        include_registry: bool = False,
    ) -> dict:
        """
        Generate docker-compose.yaml content.

        Args:
            output_path: Optional path to write the file
            include_registry: Include pactown registry service

        Returns:
            Compose file as dict
        """
        compose = {
            "version": "3.8",
            "name": self.ecosystem.name,
            "services": {},
            "networks": {
                self.deploy_config.network_name: {
                    "driver": "bridge",
                },
            },
        }

        # Add volumes section if needed
        volumes = {}

        for name, service in self.ecosystem.services.items():
            compose_service = self._create_service(name, service)
            compose["services"][name] = compose_service

            # Check for volume mounts
            if self.deploy_config.volumes_path:
                volume_name = f"{name}-data"
                volumes[volume_name] = {"driver": "local"}

        if volumes:
            compose["volumes"] = volumes

        # Add registry service if requested
        if include_registry:
            compose["services"]["registry"] = self._create_registry_service()

        # Write to file if path provided
        if output_path:
            output_path = Path(output_path)
            with open(output_path, "w") as f:
                yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

        return compose

    def _create_service(self, name: str, service: ServiceConfig) -> dict:
        """Create compose service definition."""
        self.base_path / service.readme
        sandbox_path = self.base_path / self.ecosystem.sandbox_root / name

        svc = {
            "build": {
                "context": str(sandbox_path),
                "dockerfile": "Dockerfile",
            },
            "image": f"{self.deploy_config.image_prefix}/{name}:latest",
            "container_name": f"{self.ecosystem.name}-{name}",
            "restart": "unless-stopped",
            "networks": [self.deploy_config.network_name],
        }

        # Ports
        if service.port and self.deploy_config.expose_ports:
            svc["ports"] = [f"{service.port}:{service.port}"]

        # Environment
        env = {"SERVICE_NAME": name}
        if service.port:
            env["MARKPACT_PORT"] = str(service.port)

        # Add dependency URLs
        for dep in service.depends_on:
            dep_service = self.ecosystem.services.get(dep.name)
            if dep_service:
                env_key = dep.name.upper().replace("-", "_")
                # Use container DNS name
                env[f"{env_key}_URL"] = f"http://{dep.name}:{dep_service.port}"

        env.update(service.env)
        svc["environment"] = env

        # Dependencies
        if service.depends_on:
            svc["depends_on"] = {}
            for dep in service.depends_on:
                if dep.name in self.ecosystem.services:
                    dep_svc = self.ecosystem.services[dep.name]
                    condition = "service_healthy" if dep_svc.health_check else "service_started"
                    svc["depends_on"][dep.name] = {"condition": condition}

        # Health check
        if service.health_check:
            svc["healthcheck"] = {
                "test": ["CMD", "curl", "-f", f"http://localhost:{service.port}{service.health_check}"],
                "interval": self.deploy_config.health_check_interval,
                "timeout": self.deploy_config.health_check_timeout,
                "retries": self.deploy_config.health_check_retries,
                "start_period": "10s",
            }

        # Production settings
        if self.deploy_config.mode == DeploymentMode.PRODUCTION:
            svc["deploy"] = {
                "resources": {
                    "limits": {
                        "memory": self.deploy_config.memory_limit,
                        "cpus": self.deploy_config.cpu_limit,
                    },
                    "reservations": {
                        "memory": "128M",
                        "cpus": "0.1",
                    },
                },
                "restart_policy": {
                    "condition": "on-failure",
                    "delay": "5s",
                    "max_attempts": 3,
                    "window": "120s",
                },
            }

            # Security options
            svc["security_opt"] = ["no-new-privileges:true"]

            if self.deploy_config.read_only_fs:
                svc["read_only"] = True
                svc["tmpfs"] = ["/tmp"]

            svc["cap_drop"] = self.deploy_config.drop_capabilities

            if self.deploy_config.add_capabilities:
                svc["cap_add"] = self.deploy_config.add_capabilities

        # Labels
        svc["labels"] = {
            "pactown.ecosystem": self.ecosystem.name,
            "pactown.service": name,
            **self.deploy_config.labels,
        }

        return svc

    def _create_registry_service(self) -> dict:
        """Create pactown registry service."""
        return {
            "image": "pactown/registry:latest",
            "container_name": f"{self.ecosystem.name}-registry",
            "restart": "unless-stopped",
            "ports": ["8800:8800"],
            "networks": [self.deploy_config.network_name],
            "volumes": ["registry-data:/data"],
            "environment": {
                "REGISTRY_PORT": "8800",
                "REGISTRY_DATA_DIR": "/data",
            },
            "healthcheck": {
                "test": ["CMD", "curl", "-f", "http://localhost:8800/health"],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
            },
        }

    def generate_override(
        self,
        output_path: Optional[Path] = None,
        dev_mode: bool = True,
    ) -> dict:
        """
        Generate docker-compose.override.yaml for development.

        This file is automatically merged with docker-compose.yaml
        and provides development-specific settings.
        """
        override = {
            "version": "3.8",
            "services": {},
        }

        for name, service in self.ecosystem.services.items():
            sandbox_path = self.base_path / self.ecosystem.sandbox_root / name

            svc = {}

            if dev_mode:
                # Mount source code for hot reload
                svc["volumes"] = [
                    f"{sandbox_path}:/app:z",
                ]

                # Enable debug mode
                svc["environment"] = {
                    "DEBUG": "true",
                    "LOG_LEVEL": "debug",
                }

                # Remove resource limits for development
                svc["deploy"] = None

            if svc:
                override["services"][name] = svc

        if output_path:
            output_path = Path(output_path)
            with open(output_path, "w") as f:
                yaml.dump(override, f, default_flow_style=False, sort_keys=False)

        return override

    def generate_production(
        self,
        output_path: Optional[Path] = None,
        replicas: int = 2,
    ) -> dict:
        """
        Generate docker-compose.prod.yaml for production/swarm deployment.
        """
        compose = self.generate()

        for name in compose["services"]:
            svc = compose["services"][name]

            # Add swarm-specific deploy config
            svc["deploy"] = {
                "mode": "replicated",
                "replicas": replicas,
                "update_config": {
                    "parallelism": 1,
                    "delay": "10s",
                    "failure_action": "rollback",
                    "order": "start-first",
                },
                "rollback_config": {
                    "parallelism": 1,
                    "delay": "10s",
                },
                "resources": {
                    "limits": {
                        "memory": self.deploy_config.memory_limit,
                        "cpus": self.deploy_config.cpu_limit,
                    },
                },
            }

        if output_path:
            output_path = Path(output_path)
            with open(output_path, "w") as f:
                yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

        return compose


def generate_compose_from_config(
    config_path: Path,
    output_dir: Optional[Path] = None,
    production: bool = False,
) -> dict:
    """
    Convenience function to generate compose files from pactown config.

    Args:
        config_path: Path to saas.pactown.yaml
        output_dir: Directory to write compose files
        production: Generate production configuration

    Returns:
        Generated compose dict
    """
    from ..config import load_config

    config_path = Path(config_path)
    ecosystem = load_config(config_path)

    deploy_config = (
        DeploymentConfig.for_production() if production
        else DeploymentConfig.for_development()
    )

    generator = ComposeGenerator(
        ecosystem=ecosystem,
        deploy_config=deploy_config,
        base_path=config_path.parent,
    )

    output_dir = output_dir or config_path.parent

    # Generate main compose file
    compose = generator.generate(
        output_path=output_dir / "docker-compose.yaml"
    )

    # Generate override for development
    if not production:
        generator.generate_override(
            output_path=output_dir / "docker-compose.override.yaml"
        )
    else:
        generator.generate_production(
            output_path=output_dir / "docker-compose.prod.yaml"
        )

    return compose
