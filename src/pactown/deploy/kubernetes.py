"""Kubernetes deployment backend - production-grade orchestration."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml

from ..config import CacheConfig
from .base import (
    DeploymentBackend,
    DeploymentConfig,
    DeploymentResult,
    RuntimeType,
)


class KubernetesBackend(DeploymentBackend):
    """
    Kubernetes deployment backend for production environments.

    Generates and applies Kubernetes manifests for:
    - Deployments with rolling updates
    - Services for internal/external access
    - ConfigMaps for configuration
    - Secrets for sensitive data
    - HorizontalPodAutoscaler for scaling
    - NetworkPolicies for security
    """

    def __init__(self, config: DeploymentConfig, kubeconfig: Optional[str] = None):
        super().__init__(config)
        self.kubeconfig = kubeconfig

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.KUBERNETES

    def _kubectl(self, *args: str, input_data: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run kubectl command."""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        cmd.extend(args)

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=input_data,
            timeout=60,
        )

    def is_available(self) -> bool:
        """Check if kubectl is available and cluster is reachable."""
        try:
            result = self._kubectl("cluster-info")
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
        """Build image (delegates to Docker/Podman)."""
        # K8s doesn't build images directly, use Docker or Podman
        image_name = f"{self.config.registry}/{self.config.image_prefix}/{service_name}"
        if tag:
            image_name = f"{image_name}:{tag}"
        else:
            image_name = f"{image_name}:latest"

        effective_build_args: dict[str, str] = CacheConfig.from_env(os.environ).to_docker_build_args()
        if build_args:
            effective_build_args.update(build_args)

        build_arg_flags: list[str] = []
        for key, value in effective_build_args.items():
            if value is None:
                continue
            v = str(value).strip()
            if not v:
                continue
            build_arg_flags.extend(["--build-arg", f"{key}={v}"])

        # Try podman first, then docker
        for runtime in ["podman", "docker"]:
            try:
                result = subprocess.run(
                    [runtime, "build", "-t", image_name, "-f", str(dockerfile_path), *build_arg_flags, str(context_path)],
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
            except FileNotFoundError:
                continue

        return DeploymentResult(
            success=False,
            service_name=service_name,
            runtime=self.runtime_type,
            error="No container runtime (docker/podman) available",
        )

    def push_image(
        self,
        image_name: str,
        registry: Optional[str] = None,
    ) -> DeploymentResult:
        """Push image to registry."""
        for runtime in ["podman", "docker"]:
            try:
                result = subprocess.run(
                    [runtime, "push", image_name],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    return DeploymentResult(
                        success=True,
                        service_name=image_name.split("/")[-1].split(":")[0],
                        runtime=self.runtime_type,
                        image_name=image_name,
                    )
            except FileNotFoundError:
                continue

        return DeploymentResult(
            success=False,
            service_name=image_name,
            runtime=self.runtime_type,
            error="Failed to push image",
        )

    def deploy(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> DeploymentResult:
        """Deploy to Kubernetes."""
        manifests = self.generate_manifests(
            service_name=service_name,
            image_name=image_name,
            port=port,
            env=env,
            health_check=health_check,
        )

        # Apply all manifests
        for manifest in manifests:
            manifest_yaml = yaml.dump(manifest, default_flow_style=False)
            result = self._kubectl("apply", "-f", "-", input_data=manifest_yaml)

            if result.returncode != 0:
                return DeploymentResult(
                    success=False,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    error=result.stderr,
                )

        # Get service endpoint
        result = self._kubectl(
            "get", "service", service_name,
            "-n", self.config.namespace,
            "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}",
        )

        endpoint = f"http://{result.stdout}:{port}" if result.stdout else f"http://{service_name}.{self.config.namespace}.svc.cluster.local:{port}"

        return DeploymentResult(
            success=True,
            service_name=service_name,
            runtime=self.runtime_type,
            image_name=image_name,
            endpoint=endpoint,
        )

    def stop(self, service_name: str) -> DeploymentResult:
        """Delete Kubernetes resources."""
        result = self._kubectl(
            "delete", "deployment,service,configmap",
            "-l", f"app={service_name}",
            "-n", self.config.namespace,
        )

        return DeploymentResult(
            success=result.returncode == 0,
            service_name=service_name,
            runtime=self.runtime_type,
            error=result.stderr if result.returncode != 0 else None,
        )

    def logs(self, service_name: str, tail: int = 100) -> str:
        """Get pod logs."""
        result = self._kubectl(
            "logs",
            "-l", f"app={service_name}",
            "-n", self.config.namespace,
            "--tail", str(tail),
        )
        return result.stdout + result.stderr

    def status(self, service_name: str) -> dict[str, Any]:
        """Get deployment status."""
        result = self._kubectl(
            "get", "deployment", service_name,
            "-n", self.config.namespace,
            "-o", "json",
        )

        if result.returncode != 0:
            return {"running": False, "error": "Deployment not found"}

        try:
            data = json.loads(result.stdout)
            status = data.get("status", {})
            return {
                "running": status.get("availableReplicas", 0) > 0,
                "replicas": status.get("replicas", 0),
                "available": status.get("availableReplicas", 0),
                "ready": status.get("readyReplicas", 0),
                "updated": status.get("updatedReplicas", 0),
            }
        except json.JSONDecodeError:
            return {"running": False, "error": "Failed to parse status"}

    def generate_manifests(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
        replicas: int = 2,
    ) -> list[dict]:
        """Generate Kubernetes manifests for a service."""
        labels = {
            "app": service_name,
            "managed-by": "pactown",
            **self.config.labels,
        }

        manifests = []

        # Namespace
        manifests.append({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": self.config.namespace,
                "labels": {"managed-by": "pactown"},
            },
        })

        # ConfigMap for environment variables
        if env:
            manifests.append({
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": f"{service_name}-config",
                    "namespace": self.config.namespace,
                    "labels": labels,
                },
                "data": env,
            })

        # Deployment
        container_spec = {
            "name": service_name,
            "image": image_name,
            "ports": [{"containerPort": port}],
            "resources": {
                "limits": {
                    "memory": self.config.memory_limit,
                    "cpu": self.config.cpu_limit,
                },
                "requests": {
                    "memory": "128Mi",
                    "cpu": "100m",
                },
            },
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "readOnlyRootFilesystem": self.config.read_only_fs,
                "allowPrivilegeEscalation": False,
                "capabilities": {
                    "drop": self.config.drop_capabilities,
                },
            },
        }

        if env:
            container_spec["envFrom"] = [
                {"configMapRef": {"name": f"{service_name}-config"}}
            ]

        if health_check:
            container_spec["livenessProbe"] = {
                "httpGet": {"path": health_check, "port": port},
                "initialDelaySeconds": 10,
                "periodSeconds": 10,
                "timeoutSeconds": 5,
                "failureThreshold": 3,
            }
            container_spec["readinessProbe"] = {
                "httpGet": {"path": health_check, "port": port},
                "initialDelaySeconds": 5,
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            }

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": service_name,
                "namespace": self.config.namespace,
                "labels": labels,
                "annotations": self.config.annotations,
            },
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": {"app": service_name}},
                "strategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {
                        "maxUnavailable": 0,
                        "maxSurge": 1,
                    },
                },
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [container_spec],
                        "serviceAccountName": "default",
                        "automountServiceAccountToken": False,
                    },
                },
            },
        }
        manifests.append(deployment)

        # Service
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": service_name,
                "namespace": self.config.namespace,
                "labels": labels,
            },
            "spec": {
                "selector": {"app": service_name},
                "ports": [{"port": port, "targetPort": port}],
                "type": "ClusterIP",
            },
        }
        manifests.append(service)

        # NetworkPolicy for security
        network_policy = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"{service_name}-network-policy",
                "namespace": self.config.namespace,
            },
            "spec": {
                "podSelector": {"matchLabels": {"app": service_name}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{
                    "from": [{"namespaceSelector": {"matchLabels": {"managed-by": "pactown"}}}],
                    "ports": [{"port": port}],
                }],
                "egress": [{
                    "to": [{"namespaceSelector": {"matchLabels": {"managed-by": "pactown"}}}],
                }],
            },
        }
        manifests.append(network_policy)

        return manifests

    def generate_hpa(
        self,
        service_name: str,
        min_replicas: int = 2,
        max_replicas: int = 10,
        target_cpu: int = 70,
    ) -> dict:
        """Generate HorizontalPodAutoscaler manifest."""
        return {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": f"{service_name}-hpa",
                "namespace": self.config.namespace,
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": service_name,
                },
                "minReplicas": min_replicas,
                "maxReplicas": max_replicas,
                "metrics": [{
                    "type": "Resource",
                    "resource": {
                        "name": "cpu",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": target_cpu,
                        },
                    },
                }],
            },
        }

    def save_manifests(
        self,
        service_name: str,
        manifests: list[dict],
        output_dir: Path,
    ) -> Path:
        """Save manifests to files."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"{service_name}.yaml"

        with open(output_file, "w") as f:
            for i, manifest in enumerate(manifests):
                if i > 0:
                    f.write("---\n")
                yaml.dump(manifest, f, default_flow_style=False)

        return output_file
