"""Deployment backends for pactown - Docker, Podman, Kubernetes, Quadlet, Ansible, etc."""

from .ansible import AnsibleBackend, AnsibleConfig
from .base import DeploymentBackend, DeploymentConfig, DeploymentResult
from .compose import ComposeGenerator
from .docker import DockerBackend
from .kubernetes import KubernetesBackend
from .podman import PodmanBackend
from .quadlet import (
    QuadletBackend,
    QuadletConfig,
    QuadletTemplates,
    QuadletUnit,
    generate_markdown_service_quadlet,
    generate_traefik_quadlet,
)

__all__ = [
    "AnsibleBackend",
    "AnsibleConfig",
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
