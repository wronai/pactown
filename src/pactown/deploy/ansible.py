"""Ansible deployment backend – generates playbooks and inventory for remote deploys."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .base import (
    DeploymentBackend,
    DeploymentConfig,
    DeploymentResult,
    RuntimeType,
)


# ---------------------------------------------------------------------------
# Ansible-specific config
# ---------------------------------------------------------------------------

@dataclass
class AnsibleConfig:
    """Extra Ansible-specific settings layered on top of DeploymentConfig."""

    inventory_hosts: list[str] = field(default_factory=lambda: ["localhost"])
    remote_user: str = "deploy"
    become: bool = True
    become_method: str = "sudo"
    connection: str = "ssh"  # "ssh" or "local"
    ssh_key_path: Optional[str] = None
    extra_vars: dict[str, str] = field(default_factory=dict)
    roles_path: Optional[str] = None
    galaxy_requirements: Optional[str] = None  # path to requirements.yml
    verbosity: int = 0  # -v / -vv / -vvv

    @classmethod
    def for_local(cls) -> "AnsibleConfig":
        """Config for deploying on the same machine (CI, dev)."""
        return cls(
            inventory_hosts=["localhost"],
            connection="local",
            become=False,
        )

    @classmethod
    def for_remote(
        cls,
        hosts: list[str],
        user: str = "deploy",
        ssh_key: Optional[str] = None,
    ) -> "AnsibleConfig":
        """Config for deploying to remote hosts via SSH."""
        return cls(
            inventory_hosts=hosts,
            remote_user=user,
            ssh_key_path=ssh_key,
            connection="ssh",
            become=True,
        )


# ---------------------------------------------------------------------------
# Playbook / inventory generation helpers
# ---------------------------------------------------------------------------

def generate_inventory(
    *,
    hosts: list[str],
    group_name: str = "pactown_hosts",
    remote_user: str = "deploy",
    connection: str = "ssh",
    ssh_key_path: Optional[str] = None,
) -> dict[str, Any]:
    """Build an Ansible inventory dict (YAML-serialisable)."""
    host_entries: dict[str, dict[str, Any]] = {}
    for h in hosts:
        entry: dict[str, Any] = {}
        if h in ("localhost", "127.0.0.1"):
            entry["ansible_connection"] = "local"
        host_entries[h] = entry

    group_vars: dict[str, Any] = {
        "ansible_user": remote_user,
    }
    if connection != "local":
        group_vars["ansible_connection"] = connection
    if ssh_key_path:
        group_vars["ansible_ssh_private_key_file"] = ssh_key_path

    return {
        "all": {
            "children": {
                group_name: {
                    "hosts": host_entries,
                    "vars": group_vars,
                },
            },
        },
    }


def generate_deploy_playbook(
    *,
    service_name: str,
    image_name: str,
    port: int,
    env: dict[str, str],
    health_check: Optional[str] = None,
    deploy_config: DeploymentConfig,
    ansible_config: AnsibleConfig,
) -> list[dict[str, Any]]:
    """Generate an Ansible playbook (list of plays) that deploys a container."""

    tasks: list[dict[str, Any]] = []

    # 1. Pull image
    tasks.append({
        "name": f"Pull container image {image_name}",
        "community.docker.docker_image":
            {
                "name": image_name,
                "source": "pull",
                "force_source": True,
            },
        "tags": ["pull"],
    })

    # 2. Create docker network
    tasks.append({
        "name": f"Ensure network {deploy_config.network_name}",
        "community.docker.docker_network": {
            "name": deploy_config.network_name,
            "state": "present",
        },
        "tags": ["network"],
    })

    # 3. Run container
    container_params: dict[str, Any] = {
        "name": f"{deploy_config.namespace}-{service_name}",
        "image": image_name,
        "state": "started",
        "restart_policy": "unless-stopped",
        "networks": [{"name": deploy_config.network_name}],
        "env": env,
    }

    if deploy_config.expose_ports and port:
        container_params["ports"] = [f"{port}:{port}"]

    if deploy_config.memory_limit:
        container_params["memory"] = deploy_config.memory_limit

    if deploy_config.read_only_fs:
        container_params["read_only"] = True
        container_params["tmpfs"] = ["/tmp"]

    if deploy_config.no_new_privileges:
        container_params["security_opts"] = ["no-new-privileges:true"]

    if deploy_config.drop_capabilities:
        container_params["capabilities_deny"] = deploy_config.drop_capabilities

    if health_check:
        container_params["healthcheck"] = {
            "test": ["CMD", "curl", "-f", f"http://localhost:{port}{health_check}"],
            "interval": deploy_config.health_check_interval,
            "timeout": deploy_config.health_check_timeout,
            "retries": deploy_config.health_check_retries,
        }

    tasks.append({
        "name": f"Deploy container {service_name}",
        "community.docker.docker_container": container_params,
        "tags": ["deploy"],
    })

    # 4. Wait for health
    if health_check:
        tasks.append({
            "name": f"Wait for {service_name} to be healthy",
            "ansible.builtin.uri": {
                "url": f"http://localhost:{port}{health_check}",
                "status_code": 200,
            },
            "retries": 10,
            "delay": 5,
            "register": "health_result",
            "until": "health_result.status == 200",
            "tags": ["healthcheck"],
        })

    play: dict[str, Any] = {
        "name": f"Deploy {service_name} via Pactown",
        "hosts": "pactown_hosts",
        "become": ansible_config.become,
        "tasks": tasks,
    }
    if ansible_config.become:
        play["become_method"] = ansible_config.become_method

    return [play]


def generate_teardown_playbook(
    *,
    service_name: str,
    deploy_config: DeploymentConfig,
) -> list[dict[str, Any]]:
    """Generate a playbook to stop and remove a service."""
    container_name = f"{deploy_config.namespace}-{service_name}"
    return [{
        "name": f"Teardown {service_name}",
        "hosts": "pactown_hosts",
        "become": True,
        "tasks": [
            {
                "name": f"Stop and remove container {container_name}",
                "community.docker.docker_container": {
                    "name": container_name,
                    "state": "absent",
                },
                "tags": ["stop"],
            },
        ],
    }]


def generate_build_playbook(
    *,
    service_name: str,
    dockerfile_path: str,
    context_path: str,
    image_name: str,
    build_args: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Generate a playbook that builds a container image."""
    build_params: dict[str, Any] = {
        "name": image_name,
        "source": "build",
        "build": {
            "path": context_path,
            "dockerfile": dockerfile_path,
        },
        "force_source": True,
    }
    if build_args:
        build_params["build"]["args"] = build_args

    return [{
        "name": f"Build image for {service_name}",
        "hosts": "pactown_hosts",
        "become": True,
        "tasks": [
            {
                "name": f"Build {image_name}",
                "community.docker.docker_image": build_params,
                "tags": ["build"],
            },
        ],
    }]


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class AnsibleBackend(DeploymentBackend):
    """Ansible-based deployment backend.

    Instead of running containers directly, this backend generates Ansible
    playbooks and inventory files.  When ``deploy()`` / ``stop()`` etc.
    are called it can either:

    * Write files only (``dry_run=True``, the default) – useful for CI
      pipelines that run ``ansible-playbook`` themselves.
    * Execute ``ansible-playbook`` directly (``dry_run=False``).
    """

    def __init__(
        self,
        config: DeploymentConfig,
        ansible_config: Optional[AnsibleConfig] = None,
        *,
        dry_run: bool = True,
        output_dir: Optional[Path] = None,
    ):
        super().__init__(config)
        self.ansible_config = ansible_config or AnsibleConfig.for_local()
        self.dry_run = dry_run
        self.output_dir = output_dir or Path("ansible-deploy")

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.ANSIBLE

    # -- availability -------------------------------------------------------

    def is_available(self) -> bool:
        """Check if ``ansible-playbook`` is on PATH."""
        try:
            result = subprocess.run(
                ["ansible-playbook", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    # -- image operations ---------------------------------------------------

    def build_image(
        self,
        service_name: str,
        dockerfile_path: Path,
        context_path: Path,
        tag: Optional[str] = None,
        build_args: Optional[dict[str, str]] = None,
    ) -> DeploymentResult:
        image_name = f"{self.config.image_prefix}/{service_name}"
        image_name = f"{image_name}:{tag}" if tag else f"{image_name}:latest"

        playbook = generate_build_playbook(
            service_name=service_name,
            dockerfile_path=str(dockerfile_path),
            context_path=str(context_path),
            image_name=image_name,
            build_args=build_args,
        )

        pb_path = self._write_playbook("build", playbook)

        if self.dry_run:
            return DeploymentResult(
                success=True,
                service_name=service_name,
                runtime=self.runtime_type,
                image_name=image_name,
                logs=f"Playbook written to {pb_path}",
            )

        return self._run_playbook(pb_path, service_name=service_name, image_name=image_name)

    def push_image(
        self,
        image_name: str,
        registry: Optional[str] = None,
    ) -> DeploymentResult:
        target = f"{registry}/{image_name}" if registry else image_name
        push_pb = [{
            "name": f"Push {target}",
            "hosts": "pactown_hosts",
            "become": True,
            "tasks": [{
                "name": f"Push image {target}",
                "community.docker.docker_image": {
                    "name": target,
                    "push": True,
                    "source": "local",
                },
                "tags": ["push"],
            }],
        }]

        pb_path = self._write_playbook("push", push_pb)

        if self.dry_run:
            return DeploymentResult(
                success=True,
                service_name=image_name.split("/")[-1].split(":")[0],
                runtime=self.runtime_type,
                image_name=target,
                logs=f"Playbook written to {pb_path}",
            )

        return self._run_playbook(pb_path, service_name=image_name, image_name=target)

    # -- deploy / stop ------------------------------------------------------

    def deploy(
        self,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> DeploymentResult:
        playbook = generate_deploy_playbook(
            service_name=service_name,
            image_name=image_name,
            port=port,
            env=env,
            health_check=health_check,
            deploy_config=self.config,
            ansible_config=self.ansible_config,
        )

        self._write_inventory()
        pb_path = self._write_playbook("deploy", playbook)

        if self.dry_run:
            return DeploymentResult(
                success=True,
                service_name=service_name,
                runtime=self.runtime_type,
                image_name=image_name,
                endpoint=f"http://localhost:{port}" if self.config.expose_ports else None,
                logs=f"Playbook written to {pb_path}",
            )

        return self._run_playbook(pb_path, service_name=service_name, image_name=image_name)

    def stop(self, service_name: str) -> DeploymentResult:
        playbook = generate_teardown_playbook(
            service_name=service_name,
            deploy_config=self.config,
        )
        pb_path = self._write_playbook("teardown", playbook)

        if self.dry_run:
            return DeploymentResult(
                success=True,
                service_name=service_name,
                runtime=self.runtime_type,
                logs=f"Playbook written to {pb_path}",
            )

        return self._run_playbook(pb_path, service_name=service_name)

    def logs(self, service_name: str, tail: int = 100) -> str:
        container_name = f"{self.config.namespace}-{service_name}"
        # In dry-run mode we cannot fetch logs
        if self.dry_run:
            return f"[dry-run] Would fetch last {tail} lines from {container_name}"
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout + result.stderr
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def status(self, service_name: str) -> dict[str, Any]:
        container_name = f"{self.config.namespace}-{service_name}"
        if self.dry_run:
            return {"running": False, "dry_run": True, "container": container_name}
        try:
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {"running": False, "error": "Container not found"}
            data = json.loads(result.stdout)[0]
            return {
                "running": data["State"]["Running"],
                "status": data["State"]["Status"],
                "container_id": data["Id"][:12],
            }
        except Exception:
            return {"running": False, "error": "Failed to get status"}

    # -- file I/O helpers ---------------------------------------------------

    def _write_playbook(self, name: str, playbook: list[dict[str, Any]]) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pb_path = self.output_dir / f"{name}.yml"
        pb_path.write_text(yaml.safe_dump(playbook, sort_keys=False, default_flow_style=False))
        return pb_path

    def _write_inventory(self) -> Path:
        inv = generate_inventory(
            hosts=self.ansible_config.inventory_hosts,
            remote_user=self.ansible_config.remote_user,
            connection=self.ansible_config.connection,
            ssh_key_path=self.ansible_config.ssh_key_path,
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        inv_path = self.output_dir / "inventory.yml"
        inv_path.write_text(yaml.safe_dump(inv, sort_keys=False, default_flow_style=False))
        return inv_path

    def write_all(
        self,
        *,
        service_name: str,
        image_name: str,
        port: int,
        env: dict[str, str],
        health_check: Optional[str] = None,
    ) -> dict[str, Path]:
        """Write inventory + deploy + teardown playbooks.  Returns paths."""
        inv_path = self._write_inventory()
        deploy_pb = generate_deploy_playbook(
            service_name=service_name,
            image_name=image_name,
            port=port,
            env=env,
            health_check=health_check,
            deploy_config=self.config,
            ansible_config=self.ansible_config,
        )
        deploy_path = self._write_playbook("deploy", deploy_pb)

        teardown_pb = generate_teardown_playbook(
            service_name=service_name,
            deploy_config=self.config,
        )
        teardown_path = self._write_playbook("teardown", teardown_pb)

        return {
            "inventory": inv_path,
            "deploy": deploy_path,
            "teardown": teardown_path,
        }

    # -- ansible-playbook runner --------------------------------------------

    def _run_playbook(
        self,
        playbook_path: Path,
        *,
        service_name: str = "",
        image_name: str = "",
    ) -> DeploymentResult:
        """Execute ``ansible-playbook`` against the written inventory."""
        inv_path = self.output_dir / "inventory.yml"
        cmd: list[str] = [
            "ansible-playbook",
            "-i", str(inv_path),
            str(playbook_path),
        ]
        if self.ansible_config.verbosity:
            cmd.append("-" + "v" * self.ansible_config.verbosity)
        for k, v in self.ansible_config.extra_vars.items():
            cmd.extend(["-e", f"{k}={v}"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                return DeploymentResult(
                    success=True,
                    service_name=service_name,
                    runtime=self.runtime_type,
                    image_name=image_name or None,
                    logs=result.stdout,
                )
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error=result.stderr or result.stdout,
            )
        except subprocess.TimeoutExpired:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error="ansible-playbook timed out",
            )
        except FileNotFoundError:
            return DeploymentResult(
                success=False,
                service_name=service_name,
                runtime=self.runtime_type,
                error="ansible-playbook not found in PATH",
            )
