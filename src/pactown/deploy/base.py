"""Base classes for deployment backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class RuntimeType(Enum):
    """Container runtime types."""
    LOCAL = "local"          # Local process (development)
    DOCKER = "docker"        # Docker
    PODMAN = "podman"        # Podman (rootless containers)
    KUBERNETES = "kubernetes"  # Kubernetes
    COMPOSE = "compose"      # Docker Compose / Podman Compose


class DeploymentMode(Enum):
    """Deployment environment modes."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class DeploymentConfig:
    """Configuration for deployment."""

    # Runtime settings
    runtime: RuntimeType = RuntimeType.LOCAL
    mode: DeploymentMode = DeploymentMode.DEVELOPMENT

    # Container settings
    registry: str = ""                    # Container registry URL
    namespace: str = "default"            # K8s namespace or project name
    image_prefix: str = "pactown"         # Image name prefix

    # Network settings
    network_name: str = "pactown-net"     # Container network name
    expose_ports: bool = True             # Expose ports to host
    use_internal_dns: bool = True         # Use container DNS for service discovery

    # Security settings
    rootless: bool = True                 # Use rootless containers (Podman)
    read_only_fs: bool = False            # Read-only filesystem
    no_new_privileges: bool = True        # No new privileges
    drop_capabilities: list[str] = field(default_factory=lambda: ["ALL"])
    add_capabilities: list[str] = field(default_factory=list)

    # Resource limits
    memory_limit: str = "512m"            # Memory limit per service
    cpu_limit: str = "0.5"                # CPU limit per service

    # Health check settings
    health_check_interval: str = "30s"
    health_check_timeout: str = "10s"
    health_check_retries: int = 3

    # Persistence
    volumes_path: Optional[Path] = None   # Path for persistent volumes

    # Labels and annotations
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_production(cls) -> "DeploymentConfig":
        """Create production-ready configuration."""
        return cls(
            mode=DeploymentMode.PRODUCTION,
            rootless=True,
            read_only_fs=True,
            no_new_privileges=True,
            drop_capabilities=["ALL"],
            memory_limit="1g",
            cpu_limit="1.0",
            health_check_interval="10s",
            health_check_retries=5,
        )

    @classmethod
    def for_development(cls) -> "DeploymentConfig":
        """Create development configuration."""
        return cls(
            mode=DeploymentMode.DEVELOPMENT,
            rootless=False,
            read_only_fs=False,
            expose_ports=True,
        )


@dataclass
class DeploymentResult:
    """Result of a deployment operation."""
    success: bool
    service_name: str
    runtime: RuntimeType
    container_id: Optional[str] = None
    image_name: Optional[str] = None
    endpoint: Optional[str] = None
    error: Optional[str] = None
    logs: Optional[str] = None


class DeploymentBackend(ABC):
    """Abstract base class for deployment backends."""

    def __init__(self, config: DeploymentConfig):
        self.config = config

    @property
    @abstractmethod
    def runtime_type(self) -> RuntimeType:
        """Return the runtime type."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the runtime is available."""
        pass

    @abstractmethod
    def build_image(
        self,
        service_name: str,
        dockerfile_path: Path,
        context_path: Path,
        tag: Optional[str] = None,
        build_args: Optional[dict[str, str]] = None,
    ) -> DeploymentResult:
        """Build a container image."""
        pass

    @abstractmethod
    def push_image(
        self,
        image_name: str,
        registry: Optional[str] = None,
    ) -> DeploymentResult:
        """Push image to registry."""
        pass

    @abstractmethod
    def deploy(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> DeploymentResult:
        """Deploy a service."""
        pass

    @abstractmethod
    def stop(self, service_name: str) -> DeploymentResult:
        """Stop a deployed service."""
        pass

    @abstractmethod
    def logs(self, service_name: str, tail: int = 100) -> str:
        """Get logs from a service."""
        pass

    @abstractmethod
    def status(self, service_name: str) -> dict[str, Any]:
        """Get status of a service."""
        pass

    def generate_dockerfile(
        self,
        service_name: str,
        sandbox_path: Path,
        base_image: str = "python:3.12-slim",
    ) -> Path:
        """Generate Dockerfile for a service."""
        dockerfile_content = self._create_dockerfile(
            sandbox_path, base_image
        )

        dockerfile_path = sandbox_path / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)
        return dockerfile_path

    def _create_dockerfile(
        self,
        sandbox_path: Path,
        base_image: str,
    ) -> str:
        """Create Dockerfile content."""
        # Check for requirements.txt
        has_requirements = (sandbox_path / "requirements.txt").exists()

        # Check for package.json (Node.js)
        has_package_json = (sandbox_path / "package.json").exists()

        if has_package_json:
            return self._create_node_dockerfile(sandbox_path)

        # Default Python Dockerfile
        lines = [
            f"FROM {base_image}",
            "",
            "WORKDIR /app",
            "",
            "# Security: run as non-root user",
            "RUN useradd -m -u 1000 appuser",
            "",
            "# Optional cache/proxy settings (build args)",
            "ARG PIP_INDEX_URL=",
            "ARG PIP_EXTRA_INDEX_URL=",
            "ARG PIP_TRUSTED_HOST=",
            "ARG APT_PROXY=",
            "",
            "# Make them available to subsequent RUN steps if provided",
            "ENV PIP_INDEX_URL=${PIP_INDEX_URL}",
            "ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}",
            "ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}",
            "",
            "# Configure apt proxy (optional)",
            "RUN if [ -n \"$APT_PROXY\" ]; then \\\n    printf 'Acquire::http::Proxy \"%s\";\\nAcquire::https::Proxy \"%s\";\\n' \"$APT_PROXY\" \"$APT_PROXY\" > /etc/apt/apt.conf.d/01proxy; \\\n    fi",
            "",
        ]

        if has_requirements:
            lines.extend([
                "# Install dependencies",
                "COPY requirements.txt .",
                "RUN pip install --no-cache-dir -r requirements.txt",
                "",
            ])

        lines.extend([
            "# Copy application",
            "COPY . .",
            "",
            "# Switch to non-root user",
            "USER appuser",
            "",
            "# Health check",
            'HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\',
            '    CMD python -c "import os,urllib.request; ' +
            "port=os.environ.get('MARKPACT_PORT') or os.environ.get('PORT','8000'); " +
            "urllib.request.urlopen('http://localhost:%s/health' % port, timeout=5)\"",
            "",
            "# Default command",
            'CMD ["python", "main.py"]',
        ])

        return "\n".join(lines)

    def _create_node_dockerfile(self, sandbox_path: Path) -> str:
        """Create Dockerfile for Node.js service."""
        return """FROM node:20-slim

WORKDIR /app

# Security: run as non-root user
RUN useradd -m -u 1000 appuser

# Optional cache/proxy settings (build args)
ARG NPM_CONFIG_REGISTRY=

# Make them available to subsequent RUN steps if provided
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}

# Install dependencies
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --only=production; else npm install --only=production; fi

# Copy application
COPY . .

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\
    CMD node -e "require('http').get('http://localhost:'+(process.env.MARKPACT_PORT||3000)+'/health',res=>process.exit(res.statusCode===200?0:1)).on('error',()=>process.exit(1));"

# Default command
CMD ["node", "server.js"]
"""
