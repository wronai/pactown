"""Deployment backends for pactown - Docker, Podman, Kubernetes, Quadlet, etc."""

from .base import DeploymentBackend, DeploymentConfig, DeploymentResult
from .docker import DockerBackend
from .podman import PodmanBackend
from .kubernetes import KubernetesBackend
from .compose import ComposeGenerator
from .quadlet import (
    QuadletBackend,
    QuadletConfig,
    QuadletTemplates,
    QuadletUnit,
    generate_traefik_quadlet,
    generate_markdown_service_quadlet,
)

__all__ = [
    "DeploymentBackend",
    "DeploymentConfig",
    "DeploymentResult",
    "DockerBackend",
    "PodmanBackend",
    "KubernetesBackend",
    "ComposeGenerator",
    "QuadletBackend",
    "QuadletConfig",
    "QuadletTemplates",
    "QuadletUnit",
    "generate_traefik_quadlet",
    "generate_markdown_service_quadlet",
]
