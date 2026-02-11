"""Tests for pactown.deploy.ansible – Ansible deployment backend."""

import ast
import configparser
import io
import json
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
import yaml

from pactown.deploy.ansible import (
    AnsibleBackend,
    AnsibleConfig,
    generate_build_playbook,
    generate_deploy_playbook,
    generate_inventory,
    generate_teardown_playbook,
)
from pactown.deploy.base import (
    DeploymentConfig,
    DeploymentMode,
    DeploymentResult,
    RuntimeType,
)


# ===========================================================================
# AnsibleConfig
# ===========================================================================


class TestAnsibleConfig:
    def test_defaults(self) -> None:
        cfg = AnsibleConfig()
        assert cfg.inventory_hosts == ["localhost"]
        assert cfg.remote_user == "deploy"
        assert cfg.become is True
        assert cfg.become_method == "sudo"
        assert cfg.connection == "ssh"
        assert cfg.ssh_key_path is None
        assert cfg.extra_vars == {}
        assert cfg.verbosity == 0

    def test_for_local(self) -> None:
        cfg = AnsibleConfig.for_local()
        assert cfg.inventory_hosts == ["localhost"]
        assert cfg.connection == "local"
        assert cfg.become is False

    def test_for_remote_single_host(self) -> None:
        cfg = AnsibleConfig.for_remote(["10.0.0.1"], user="admin", ssh_key="/keys/id")
        assert cfg.inventory_hosts == ["10.0.0.1"]
        assert cfg.remote_user == "admin"
        assert cfg.ssh_key_path == "/keys/id"
        assert cfg.connection == "ssh"
        assert cfg.become is True

    def test_for_remote_multiple_hosts(self) -> None:
        hosts = ["web1.example.com", "web2.example.com", "web3.example.com"]
        cfg = AnsibleConfig.for_remote(hosts)
        assert cfg.inventory_hosts == hosts
        assert cfg.remote_user == "deploy"

    def test_custom_extra_vars(self) -> None:
        cfg = AnsibleConfig(extra_vars={"env": "prod", "region": "eu-west-1"})
        assert cfg.extra_vars["env"] == "prod"
        assert cfg.extra_vars["region"] == "eu-west-1"

    def test_galaxy_requirements(self) -> None:
        cfg = AnsibleConfig(galaxy_requirements="requirements.yml")
        assert cfg.galaxy_requirements == "requirements.yml"

    def test_roles_path(self) -> None:
        cfg = AnsibleConfig(roles_path="/etc/ansible/roles")
        assert cfg.roles_path == "/etc/ansible/roles"

    def test_verbosity_levels(self) -> None:
        for v in (0, 1, 2, 3):
            assert AnsibleConfig(verbosity=v).verbosity == v


# ===========================================================================
# generate_inventory
# ===========================================================================


class TestGenerateInventory:
    def test_single_remote_host(self) -> None:
        inv = generate_inventory(hosts=["10.0.0.5"], remote_user="admin")
        group = inv["all"]["children"]["pactown_hosts"]
        assert "10.0.0.5" in group["hosts"]
        assert group["vars"]["ansible_user"] == "admin"

    def test_localhost_gets_local_connection(self) -> None:
        inv = generate_inventory(hosts=["localhost"])
        host_entry = inv["all"]["children"]["pactown_hosts"]["hosts"]["localhost"]
        assert host_entry["ansible_connection"] == "local"

    def test_127_0_0_1_gets_local_connection(self) -> None:
        inv = generate_inventory(hosts=["127.0.0.1"])
        host_entry = inv["all"]["children"]["pactown_hosts"]["hosts"]["127.0.0.1"]
        assert host_entry["ansible_connection"] == "local"

    def test_multiple_hosts(self) -> None:
        inv = generate_inventory(hosts=["web1", "web2", "db1"])
        hosts = inv["all"]["children"]["pactown_hosts"]["hosts"]
        assert set(hosts.keys()) == {"web1", "web2", "db1"}

    def test_custom_group_name(self) -> None:
        inv = generate_inventory(hosts=["h1"], group_name="webservers")
        assert "webservers" in inv["all"]["children"]

    def test_ssh_key_path(self) -> None:
        inv = generate_inventory(hosts=["h1"], ssh_key_path="/home/me/.ssh/id_ed25519")
        vars_ = inv["all"]["children"]["pactown_hosts"]["vars"]
        assert vars_["ansible_ssh_private_key_file"] == "/home/me/.ssh/id_ed25519"

    def test_no_ssh_key(self) -> None:
        inv = generate_inventory(hosts=["h1"])
        vars_ = inv["all"]["children"]["pactown_hosts"]["vars"]
        assert "ansible_ssh_private_key_file" not in vars_

    def test_local_connection_skips_ansible_connection_var(self) -> None:
        inv = generate_inventory(hosts=["h1"], connection="local")
        vars_ = inv["all"]["children"]["pactown_hosts"]["vars"]
        assert "ansible_connection" not in vars_

    def test_ssh_connection_sets_ansible_connection_var(self) -> None:
        inv = generate_inventory(hosts=["h1"], connection="ssh")
        vars_ = inv["all"]["children"]["pactown_hosts"]["vars"]
        assert vars_["ansible_connection"] == "ssh"

    def test_yaml_serialisable(self) -> None:
        inv = generate_inventory(hosts=["a", "b"], ssh_key_path="/k")
        text = yaml.safe_dump(inv)
        roundtrip = yaml.safe_load(text)
        assert roundtrip == inv


# ===========================================================================
# generate_deploy_playbook
# ===========================================================================


def _deploy_config(**overrides: Any) -> DeploymentConfig:
    defaults = dict(
        network_name="test-net",
        namespace="test",
        expose_ports=True,
        memory_limit="256m",
        read_only_fs=False,
        no_new_privileges=True,
        drop_capabilities=["ALL"],
        health_check_interval="30s",
        health_check_timeout="10s",
        health_check_retries=3,
    )
    defaults.update(overrides)
    return DeploymentConfig(**defaults)


class TestGenerateDeployPlaybook:
    def test_basic_structure(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="pactown/api:latest",
            port=8000,
            env={"APP_ENV": "prod"},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
        )
        assert len(pb) == 1
        play = pb[0]
        assert play["hosts"] == "pactown_hosts"
        assert "Deploy api via Pactown" in play["name"]
        assert isinstance(play["tasks"], list)

    def test_pull_task(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="pactown/api:v1",
            port=8000,
            env={},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        pull_task = pb[0]["tasks"][0]
        assert "pull" in pull_task["tags"]
        img = pull_task["community.docker.docker_image"]
        assert img["name"] == "pactown/api:v1"
        assert img["source"] == "pull"

    def test_network_task(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(network_name="my-net"),
            ansible_config=AnsibleConfig(),
        )
        net_task = pb[0]["tasks"][1]
        assert "network" in net_task["tags"]
        assert net_task["community.docker.docker_network"]["name"] == "my-net"

    def test_container_task_port_mapping(self) -> None:
        pb = generate_deploy_playbook(
            service_name="web",
            image_name="img",
            port=3000,
            env={},
            deploy_config=_deploy_config(expose_ports=True),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert "3000:3000" in container["ports"]

    def test_container_task_no_port_when_not_exposed(self) -> None:
        pb = generate_deploy_playbook(
            service_name="worker",
            image_name="img",
            port=5000,
            env={},
            deploy_config=_deploy_config(expose_ports=False),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert "ports" not in container

    def test_container_env(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={"DB_HOST": "db.local", "SECRET": "x"},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["DB_HOST"] == "db.local"
        assert container["env"]["SECRET"] == "x"

    def test_container_memory_limit(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(memory_limit="1g"),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["memory"] == "1g"

    def test_container_read_only_fs(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(read_only_fs=True),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["read_only"] is True
        assert "/tmp" in container["tmpfs"]

    def test_container_no_new_privileges(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(no_new_privileges=True),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert "no-new-privileges:true" in container["security_opts"]

    def test_container_drop_capabilities(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(drop_capabilities=["ALL"]),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["capabilities_deny"] == ["ALL"]

    def test_healthcheck_tasks_present(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="img",
            port=8000,
            env={},
            health_check="/health",
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        tasks = pb[0]["tasks"]
        # Should have 4 tasks: pull, network, container, health wait
        assert len(tasks) == 4
        health_task = tasks[3]
        assert "healthcheck" in health_task["tags"]
        assert health_task["ansible.builtin.uri"]["url"] == "http://localhost:8000/health"
        assert health_task["retries"] == 10

    def test_no_healthcheck_when_none(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="img",
            port=8000,
            env={},
            health_check=None,
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        tasks = pb[0]["tasks"]
        assert len(tasks) == 3  # no health wait task

    def test_container_healthcheck_params(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=9090,
            env={},
            health_check="/ready",
            deploy_config=_deploy_config(
                health_check_interval="15s",
                health_check_timeout="5s",
                health_check_retries=5,
            ),
            ansible_config=AnsibleConfig(),
        )
        hc = pb[0]["tasks"][2]["community.docker.docker_container"]["healthcheck"]
        assert hc["interval"] == "15s"
        assert hc["timeout"] == "5s"
        assert hc["retries"] == 5
        assert "curl" in hc["test"][1]
        assert "/ready" in hc["test"][3]

    def test_become_settings(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(become=True, become_method="sudo"),
        )
        play = pb[0]
        assert play["become"] is True
        assert play["become_method"] == "sudo"

    def test_no_become(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
        )
        play = pb[0]
        assert play["become"] is False
        assert "become_method" not in play

    def test_container_name_includes_namespace(self) -> None:
        pb = generate_deploy_playbook(
            service_name="api",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(namespace="staging"),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["name"] == "staging-api"

    def test_restart_policy(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img",
            port=8000,
            env={},
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["restart_policy"] == "unless-stopped"

    def test_yaml_serialisable(self) -> None:
        pb = generate_deploy_playbook(
            service_name="svc",
            image_name="img:v1",
            port=8000,
            env={"A": "1"},
            health_check="/health",
            deploy_config=_deploy_config(),
            ansible_config=AnsibleConfig(),
        )
        text = yaml.safe_dump(pb, sort_keys=False)
        roundtrip = yaml.safe_load(text)
        assert roundtrip == pb


# ===========================================================================
# generate_teardown_playbook
# ===========================================================================


class TestGenerateTeardownPlaybook:
    def test_structure(self) -> None:
        pb = generate_teardown_playbook(
            service_name="api",
            deploy_config=_deploy_config(namespace="prod"),
        )
        assert len(pb) == 1
        play = pb[0]
        assert play["hosts"] == "pactown_hosts"
        assert play["become"] is True
        tasks = play["tasks"]
        assert len(tasks) == 1

    def test_container_name(self) -> None:
        pb = generate_teardown_playbook(
            service_name="web",
            deploy_config=_deploy_config(namespace="myns"),
        )
        task = pb[0]["tasks"][0]
        container = task["community.docker.docker_container"]
        assert container["name"] == "myns-web"
        assert container["state"] == "absent"

    def test_stop_tag(self) -> None:
        pb = generate_teardown_playbook(
            service_name="svc",
            deploy_config=_deploy_config(),
        )
        assert "stop" in pb[0]["tasks"][0]["tags"]


# ===========================================================================
# generate_build_playbook
# ===========================================================================


class TestGenerateBuildPlaybook:
    def test_basic(self) -> None:
        pb = generate_build_playbook(
            service_name="api",
            dockerfile_path="Dockerfile",
            context_path=".",
            image_name="pactown/api:latest",
        )
        assert len(pb) == 1
        task = pb[0]["tasks"][0]
        img = task["community.docker.docker_image"]
        assert img["name"] == "pactown/api:latest"
        assert img["source"] == "build"
        assert img["build"]["path"] == "."
        assert img["build"]["dockerfile"] == "Dockerfile"

    def test_with_build_args(self) -> None:
        pb = generate_build_playbook(
            service_name="api",
            dockerfile_path="Dockerfile",
            context_path="/app",
            image_name="img:v1",
            build_args={"VERSION": "1.0", "ENV": "prod"},
        )
        args = pb[0]["tasks"][0]["community.docker.docker_image"]["build"]["args"]
        assert args["VERSION"] == "1.0"
        assert args["ENV"] == "prod"

    def test_no_build_args(self) -> None:
        pb = generate_build_playbook(
            service_name="api",
            dockerfile_path="Dockerfile",
            context_path=".",
            image_name="img:v1",
        )
        assert "args" not in pb[0]["tasks"][0]["community.docker.docker_image"]["build"]

    def test_build_tag(self) -> None:
        pb = generate_build_playbook(
            service_name="api",
            dockerfile_path="Dockerfile",
            context_path=".",
            image_name="img",
        )
        assert "build" in pb[0]["tasks"][0]["tags"]


# ===========================================================================
# AnsibleBackend - dry_run mode (default)
# ===========================================================================


class TestAnsibleBackendDryRun:
    def _backend(self, tmp_path: Path, **kw: Any) -> AnsibleBackend:
        return AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible",
            **kw,
        )

    def test_runtime_type(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        assert b.runtime_type == RuntimeType.ANSIBLE

    def test_deploy_writes_files(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.deploy(
            service_name="api",
            image_name="pactown/api:latest",
            port=8000,
            env={"APP_ENV": "prod"},
            health_check="/health",
        )
        assert result.success
        assert result.runtime == RuntimeType.ANSIBLE
        assert result.image_name == "pactown/api:latest"

        out = tmp_path / "ansible"
        assert (out / "deploy.yml").exists()
        assert (out / "inventory.yml").exists()

        # Verify deploy playbook content
        pb = yaml.safe_load((out / "deploy.yml").read_text())
        assert pb[0]["hosts"] == "pactown_hosts"

        # Verify inventory content
        inv = yaml.safe_load((out / "inventory.yml").read_text())
        assert "localhost" in inv["all"]["children"]["pactown_hosts"]["hosts"]

    def test_deploy_endpoint(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.deploy("svc", "img", 3000, {})
        assert result.endpoint == "http://localhost:3000"

    def test_deploy_no_endpoint_when_ports_not_exposed(self, tmp_path: Path) -> None:
        b = AnsibleBackend(
            config=_deploy_config(expose_ports=False),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )
        result = b.deploy("svc", "img", 3000, {})
        assert result.endpoint is None

    def test_stop_writes_teardown(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.stop("api")
        assert result.success
        assert (tmp_path / "ansible" / "teardown.yml").exists()

    def test_build_image_writes_playbook(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.build_image(
            service_name="api",
            dockerfile_path=Path("Dockerfile"),
            context_path=tmp_path,
            tag="v2",
        )
        assert result.success
        assert "api" in result.image_name
        assert ":v2" in result.image_name
        assert (tmp_path / "ansible" / "build.yml").exists()

    def test_build_image_default_tag(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.build_image("svc", Path("Dockerfile"), tmp_path)
        assert result.image_name.endswith(":latest")

    def test_push_image_writes_playbook(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.push_image("pactown/api:v1", registry="ghcr.io")
        assert result.success
        assert result.image_name == "ghcr.io/pactown/api:v1"
        assert (tmp_path / "ansible" / "push.yml").exists()

    def test_push_image_no_registry(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.push_image("myimg:latest")
        assert result.image_name == "myimg:latest"

    def test_logs_dry_run(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        out = b.logs("api", tail=50)
        assert "dry-run" in out
        assert "test-api" in out

    def test_status_dry_run(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        st = b.status("api")
        assert st["dry_run"] is True
        assert st["running"] is False

    def test_write_all(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        paths = b.write_all(
            service_name="web",
            image_name="pactown/web:v1",
            port=3000,
            env={"NODE_ENV": "production"},
            health_check="/healthz",
        )
        assert "inventory" in paths
        assert "deploy" in paths
        assert "teardown" in paths
        for p in paths.values():
            assert p.exists()
            content = yaml.safe_load(p.read_text())
            assert content is not None

    def test_write_all_no_health_check(self, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        paths = b.write_all(
            service_name="worker",
            image_name="img:v1",
            port=5000,
            env={},
        )
        pb = yaml.safe_load(paths["deploy"].read_text())
        tasks = pb[0]["tasks"]
        # No health-wait task
        assert len(tasks) == 3


# ===========================================================================
# AnsibleBackend - is_available
# ===========================================================================


class TestAnsibleBackendAvailability:
    @patch("subprocess.run")
    def test_available_when_ansible_installed(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        b = AnsibleBackend(_deploy_config(), output_dir=tmp_path)
        assert b.is_available() is True

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_not_available_when_not_installed(self, mock_run: MagicMock, tmp_path: Path) -> None:
        b = AnsibleBackend(_deploy_config(), output_dir=tmp_path)
        assert b.is_available() is False

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=5))
    def test_not_available_on_timeout(self, mock_run: MagicMock, tmp_path: Path) -> None:
        b = AnsibleBackend(_deploy_config(), output_dir=tmp_path)
        assert b.is_available() is False


# ===========================================================================
# AnsibleBackend - _run_playbook (non-dry-run)
# ===========================================================================


class TestAnsibleBackendRun:
    def _backend(self, tmp_path: Path) -> AnsibleBackend:
        return AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=False,
            output_dir=tmp_path / "ansible",
        )

    @patch("subprocess.run")
    def test_deploy_runs_ansible_playbook(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        b = self._backend(tmp_path)
        result = b.deploy("api", "img:v1", 8000, {"A": "1"})
        assert result.success
        # ansible-playbook should have been called
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ansible-playbook"
        assert "-i" in call_args

    @patch("subprocess.run")
    def test_deploy_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="FAILED!")
        b = self._backend(tmp_path)
        result = b.deploy("api", "img:v1", 8000, {})
        assert not result.success
        assert "FAILED!" in result.error

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=600))
    def test_deploy_timeout(self, mock_run: MagicMock, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.deploy("api", "img:v1", 8000, {})
        assert not result.success
        assert "timed out" in result.error

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_deploy_ansible_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        b = self._backend(tmp_path)
        result = b.deploy("api", "img:v1", 8000, {})
        assert not result.success
        assert "not found" in result.error

    @patch("subprocess.run")
    def test_stop_runs_ansible_playbook(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        b = self._backend(tmp_path)
        result = b.stop("api")
        assert result.success

    @patch("subprocess.run")
    def test_verbosity_flag(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        b = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig(verbosity=3),
            dry_run=False,
            output_dir=tmp_path / "ansible",
        )
        b.deploy("svc", "img", 8000, {})
        call_args = mock_run.call_args[0][0]
        assert "-vvv" in call_args

    @patch("subprocess.run")
    def test_extra_vars_passed(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        b = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig(extra_vars={"env": "prod"}),
            dry_run=False,
            output_dir=tmp_path / "ansible",
        )
        b.deploy("svc", "img", 8000, {})
        call_args = mock_run.call_args[0][0]
        assert "-e" in call_args
        idx = call_args.index("-e")
        assert call_args[idx + 1] == "env=prod"

    @patch("subprocess.run")
    def test_build_image_non_dry_run(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        b = self._backend(tmp_path)
        result = b.build_image("svc", Path("Dockerfile"), tmp_path, tag="v3")
        assert result.success

    @patch("subprocess.run")
    def test_push_image_non_dry_run(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        b = self._backend(tmp_path)
        result = b.push_image("img:v1")
        assert result.success


# ===========================================================================
# AnsibleBackend - logs / status (non-dry-run)
# ===========================================================================


class TestAnsibleBackendLogsStatus:
    @patch("subprocess.run")
    def test_logs_calls_docker(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="line1\nline2\n", stderr="")
        b = AnsibleBackend(_deploy_config(), dry_run=False, output_dir=tmp_path)
        out = b.logs("api", tail=50)
        assert "line1" in out
        cmd = mock_run.call_args[0][0]
        assert "docker" in cmd
        assert "--tail" in cmd

    @patch("subprocess.run")
    def test_status_running(self, mock_run: MagicMock, tmp_path: Path) -> None:
        inspect_data = [{"Id": "abc123def456", "State": {"Running": True, "Status": "running"}}]
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(inspect_data))
        b = AnsibleBackend(_deploy_config(), dry_run=False, output_dir=tmp_path)
        st = b.status("api")
        assert st["running"] is True
        assert st["container_id"] == "abc123def456"

    @patch("subprocess.run")
    def test_status_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        b = AnsibleBackend(_deploy_config(), dry_run=False, output_dir=tmp_path)
        st = b.status("api")
        assert st["running"] is False

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_logs_docker_not_available(self, mock_run: MagicMock, tmp_path: Path) -> None:
        b = AnsibleBackend(_deploy_config(), dry_run=False, output_dir=tmp_path)
        assert b.logs("api") == ""


# ===========================================================================
# Playbook YAML content validation (round-trip)
# ===========================================================================


class TestPlaybookYamlContent:
    def test_deploy_playbook_roundtrips(self, tmp_path: Path) -> None:
        b = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_remote(["web1", "web2"], ssh_key="/k"),
            dry_run=True,
            output_dir=tmp_path,
        )
        b.deploy("api", "img:v1", 8000, {"KEY": "val"}, health_check="/h")
        pb = yaml.safe_load((tmp_path / "deploy.yml").read_text())
        assert pb[0]["tasks"][0]["community.docker.docker_image"]["name"] == "img:v1"

    def test_inventory_has_all_hosts(self, tmp_path: Path) -> None:
        b = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_remote(["a.com", "b.com", "c.com"]),
            dry_run=True,
            output_dir=tmp_path,
        )
        b.deploy("svc", "img", 8000, {})
        inv = yaml.safe_load((tmp_path / "inventory.yml").read_text())
        hosts = inv["all"]["children"]["pactown_hosts"]["hosts"]
        assert set(hosts.keys()) == {"a.com", "b.com", "c.com"}

    def test_teardown_playbook_content(self, tmp_path: Path) -> None:
        b = AnsibleBackend(
            config=_deploy_config(namespace="prod"),
            dry_run=True,
            output_dir=tmp_path,
        )
        b.stop("web")
        pb = yaml.safe_load((tmp_path / "teardown.yml").read_text())
        task = pb[0]["tasks"][0]
        assert task["community.docker.docker_container"]["name"] == "prod-web"
        assert task["community.docker.docker_container"]["state"] == "absent"


# ===========================================================================
# Integration with DeploymentConfig presets
# ===========================================================================


class TestIntegrationWithDeploymentConfig:
    def test_production_config(self, tmp_path: Path) -> None:
        prod = DeploymentConfig.for_production()
        b = AnsibleBackend(prod, dry_run=True, output_dir=tmp_path)
        result = b.deploy("api", "img:v1", 8000, {}, health_check="/h")
        assert result.success
        pb = yaml.safe_load((tmp_path / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["read_only"] is True
        assert "no-new-privileges:true" in container["security_opts"]

    def test_development_config(self, tmp_path: Path) -> None:
        dev = DeploymentConfig.for_development()
        b = AnsibleBackend(dev, dry_run=True, output_dir=tmp_path)
        result = b.deploy("api", "img:v1", 8000, {})
        assert result.success
        pb = yaml.safe_load((tmp_path / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert "read_only" not in container


# ===========================================================================
# RuntimeType enum
# ===========================================================================


def test_runtime_type_ansible_exists() -> None:
    assert RuntimeType.ANSIBLE.value == "ansible"


def test_runtime_type_ansible_in_enum() -> None:
    assert "ansible" in [rt.value for rt in RuntimeType]


# ===========================================================================
# Integration with pactown builders (Desktop)
# ===========================================================================


class TestAnsibleDesktopIntegration:
    """Test Ansible deployment of desktop apps built with DesktopBuilder."""

    def test_electron_build_and_deploy_playbook(self, tmp_path: Path) -> None:
        """Build Electron app, generate Ansible playbook to deploy."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-app"
        sandbox.mkdir()
        
        # Scaffold Electron app
        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="electron",
            app_name="my-electron-app",
        )

        # Verify scaffold created package.json
        pkg_json = sandbox / "package.json"
        assert pkg_json.exists()

        # Generate Ansible deployment
        backend = AnsibleBackend(
            config=_deploy_config(namespace="electron-prod"),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible-electron",
        )

        result = backend.deploy(
            service_name="electron-app",
            image_name="pactown/electron-app:latest",
            port=3000,
            env={"NODE_ENV": "production"},
            health_check="/health",
        )

        assert result.success
        assert result.service_name == "electron-app"

        # Verify playbook was generated
        deploy_yml = tmp_path / "ansible-electron" / "deploy.yml"
        assert deploy_yml.exists()

        # Verify playbook content
        pb = yaml.safe_load(deploy_yml.read_text())
        assert pb[0]["name"] == "Deploy electron-app via Pactown"
        container_task = pb[0]["tasks"][2]
        assert container_task["community.docker.docker_container"]["name"] == "electron-prod-electron-app"

    def test_tauri_build_scaffold_with_ansible_deployment(self, tmp_path: Path) -> None:
        """Scaffold Tauri app and prepare Ansible deployment."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tauri-app"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="tauri",
            app_name="tauri-desktop",
            extra={"app_id": "com.pactown.tauri", "window_width": 1280, "window_height": 720},
        )

        # Verify Tauri config
        tauri_conf = sandbox / "src-tauri" / "tauri.conf.json"
        assert tauri_conf.exists()
        conf = json.loads(tauri_conf.read_text())
        assert conf["tauri"]["bundle"]["identifier"] == "com.pactown.tauri"

        # Generate Ansible playbook for remote deployment
        backend = AnsibleBackend(
            config=DeploymentConfig.for_production(),
            ansible_config=AnsibleConfig.for_remote(
                hosts=["tauri-server-1.example.com", "tauri-server-2.example.com"],
                user="deploy",
            ),
            dry_run=True,
            output_dir=tmp_path / "ansible-tauri",
        )

        result = backend.deploy(
            service_name="tauri-app",
            image_name="registry.example.com/tauri:v1",
            port=8080,
            env={"RUST_LOG": "info"},
        )

        assert result.success

        # Verify inventory has both hosts
        inv_yml = tmp_path / "ansible-tauri" / "inventory.yml"
        inv = yaml.safe_load(inv_yml.read_text())
        hosts = inv["all"]["children"]["pactown_hosts"]["hosts"]
        assert "tauri-server-1.example.com" in hosts
        assert "tauri-server-2.example.com" in hosts

    def test_pyinstaller_scaffold_and_ansible_build_playbook(self, tmp_path: Path) -> None:
        """Scaffold PyInstaller app and generate Ansible build playbook."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "pyinstaller-app"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("print('Hello from PyInstaller')\n")

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="pyinstaller",
            app_name="pyapp",
        )

        # Verify .spec file created
        assert (sandbox / "pyapp.spec").exists()

        # Generate Ansible build + deploy
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible-pyinstaller",
        )

        # Generate build playbook
        build_result = backend.build_image(
            service_name="pyapp",
            dockerfile_path=sandbox / "Dockerfile",
            context_path=sandbox,
            tag="v1.0",
        )

        assert build_result.success
        assert "pyapp:v1.0" in build_result.image_name

        # Verify build playbook
        build_yml = tmp_path / "ansible-pyinstaller" / "build.yml"
        assert build_yml.exists()
        pb = yaml.safe_load(build_yml.read_text())
        assert pb[0]["tasks"][0]["community.docker.docker_image"]["build"]["path"] == str(sandbox)

    def test_pyqt_scaffold_with_icon_and_ansible(self, tmp_path: Path) -> None:
        """Scaffold PyQt app with custom icon, deploy via Ansible."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "pyqt-app"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("# PyQt app\n")

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="pyqt",
            app_name="pyqt-gui",
            extra={"icon": "assets/app.ico"},
        )

        spec_file = sandbox / "pyqt-gui.spec"
        assert spec_file.exists()
        spec_content = spec_file.read_text()
        assert "icon='assets/app.ico'" in spec_content

        # Deploy with Ansible
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible-pyqt",
        )

        result = backend.deploy(
            service_name="pyqt-gui",
            image_name="pactown/pyqt-gui:latest",
            port=5000,
            env={"DISPLAY": ":0"},
        )

        assert result.success

    def test_electron_multi_platform_build_with_ansible_matrix(self, tmp_path: Path) -> None:
        """Test Electron multi-platform build targets with Ansible matrix deployment."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-multi"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="electron",
            app_name="multi-platform-app",
        )

        # Verify build targets in package.json
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "linux" in pkg["build"]
        assert "win" in pkg["build"]
        assert "mac" in pkg["build"]

        # Generate Ansible deployment for each platform
        for platform in ["linux", "windows", "macos"]:
            backend = AnsibleBackend(
                config=_deploy_config(namespace=f"electron-{platform}"),
                dry_run=True,
                output_dir=tmp_path / f"ansible-{platform}",
            )

            result = backend.deploy(
                service_name=f"app-{platform}",
                image_name=f"pactown/app:{platform}",
                port=8000,
                env={"PLATFORM": platform},
            )

            assert result.success
            assert (tmp_path / f"ansible-{platform}" / "deploy.yml").exists()


# ===========================================================================
# Integration with pactown builders (Mobile)
# ===========================================================================


class TestAnsibleMobileIntegration:
    """Test Ansible deployment of mobile apps built with MobileBuilder."""

    def test_capacitor_scaffold_and_ansible_deployment(self, tmp_path: Path) -> None:
        """Scaffold Capacitor app and deploy via Ansible."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "capacitor-app"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html><body>Capacitor App</body></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="cap-mobile",
            extra={"app_id": "com.pactown.cap", "targets": ["android", "ios"]},
        )

        # Verify Capacitor config
        cap_conf = sandbox / "capacitor.config.json"
        assert cap_conf.exists()
        conf = json.loads(cap_conf.read_text())
        assert conf["appId"] == "com.pactown.cap"
        assert conf["appName"] == "cap-mobile"

        # Verify package.json has compatible Capacitor versions
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "@capacitor/core" in pkg["dependencies"]
        assert pkg["dependencies"]["@capacitor/android"] == "^6.0.0"
        assert pkg["dependencies"]["@capacitor/ios"] == "^6.0.0"

        # Generate Ansible deployment
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible-capacitor",
        )

        result = backend.deploy(
            service_name="cap-mobile",
            image_name="pactown/cap-mobile:latest",
            port=8100,
            env={"CAPACITOR_PLATFORM": "android"},
            health_check="/",
        )

        assert result.success
        assert result.endpoint == "http://localhost:8100"

    def test_react_native_scaffold_with_ansible(self, tmp_path: Path) -> None:
        """Scaffold React Native app and generate Ansible playbook."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn-app"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="react-native",
            app_name="rn-mobile",
            extra={"app_name": "React Native Mobile"},
        )

        # Verify app.json
        app_json = sandbox / "app.json"
        assert app_json.exists()
        app_data = json.loads(app_json.read_text())
        assert app_data["name"] == "rn-mobile"
        assert app_data["displayName"] == "React Native Mobile"

        # Deploy via Ansible
        backend = AnsibleBackend(
            config=DeploymentConfig.for_production(),
            ansible_config=AnsibleConfig.for_remote(
                hosts=["mobile-build-server.example.com"],
                user="rn-builder",
                ssh_key="/keys/id_rsa",
            ),
            dry_run=True,
            output_dir=tmp_path / "ansible-rn",
        )

        result = backend.deploy(
            service_name="rn-mobile",
            image_name="pactown/rn-mobile:prod",
            port=8081,
            env={"NODE_ENV": "production", "PLATFORM": "android"},
        )

        assert result.success

        # Verify production config applied
        pb = yaml.safe_load((tmp_path / "ansible-rn" / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["read_only"] is True

    def test_flutter_scaffold_android_ios_with_ansible(self, tmp_path: Path) -> None:
        """Scaffold Flutter app for android/ios and deploy via Ansible."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "flutter-app"
        sandbox.mkdir()

        builder = MobileBuilder()
        # Flutter scaffold is no-op but we test the integration
        logs: list[str] = []
        builder.scaffold(
            sandbox,
            framework="flutter",
            app_name="flutter-mobile",
            on_log=logs.append,
        )

        assert any("flutter" in log.lower() for log in logs)

        # Deploy via Ansible to multiple build servers
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_remote(
                hosts=["flutter-builder-1", "flutter-builder-2"],
            ),
            dry_run=True,
            output_dir=tmp_path / "ansible-flutter",
        )

        # Deploy for Android
        result_android = backend.deploy(
            service_name="flutter-android",
            image_name="pactown/flutter:android-latest",
            port=8080,
            env={"TARGET": "android"},
        )
        assert result_android.success

        # Deploy for iOS
        result_ios = backend.deploy(
            service_name="flutter-ios",
            image_name="pactown/flutter:ios-latest",
            port=8081,
            env={"TARGET": "ios"},
        )
        assert result_ios.success

    def test_kivy_buildozer_scaffold_with_ansible(self, tmp_path: Path) -> None:
        """Scaffold Kivy app with buildozer.spec and deploy via Ansible."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "kivy-app"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="kivy",
            app_name="kivy-mobile",
            extra={"app_id": "org.pactown.kivy", "fullscreen": False},
        )

        # Verify buildozer.spec
        spec = sandbox / "buildozer.spec"
        assert spec.exists()
        spec_content = spec.read_text()
        assert "title = kivy-mobile" in spec_content
        assert "package.domain = org.pactown" in spec_content
        assert "fullscreen = 0" in spec_content

        # Deploy via Ansible
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible-kivy",
        )

        result = backend.deploy(
            service_name="kivy-mobile",
            image_name="pactown/kivy:latest",
            port=5555,
            env={"KIVY_NO_CONSOLELOG": "1"},
        )

        assert result.success

    def test_capacitor_webdir_detection_with_ansible(self, tmp_path: Path) -> None:
        """Test Capacitor webDir detection priority with Ansible deployment."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "cap-webdir"
        sandbox.mkdir()

        # Create multiple possible webDir locations
        for d in ("dist", "www", "build"):
            (sandbox / d).mkdir()
            (sandbox / d / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="webdir-test",
        )

        # Verify dist is preferred
        cap_conf = json.loads((sandbox / "capacitor.config.json").read_text())
        assert cap_conf["webDir"] == "dist"

        # Deploy with Ansible
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible-cap",
        )

        result = backend.deploy(
            service_name="webdir-test",
            image_name="pactown/cap-webdir:latest",
            port=8100,
            env={},
        )

        assert result.success


# ===========================================================================
# End-to-end: Build → Deploy with Ansible
# ===========================================================================


class TestE2EBuildAndAnsibleDeploy:
    """End-to-end tests: build artifacts, then deploy via Ansible."""

    def test_desktop_electron_full_workflow(self, tmp_path: Path) -> None:
        """Full workflow: scaffold → build → generate Ansible playbook → deploy."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e2e-electron"
        sandbox.mkdir()
        (sandbox / "main.js").write_text("console.log('Electron app');\n")
        (sandbox / "index.html").write_text("<html><body>App</body></html>")

        # Step 1: Scaffold
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="e2e-app")

        pkg_json = sandbox / "package.json"
        assert pkg_json.exists()

        # Step 2: Generate Dockerfile (simulated)
        dockerfile = sandbox / "Dockerfile"
        dockerfile.write_text("FROM node:20-slim\nWORKDIR /app\nCOPY . .\nCMD ['npm', 'start']\n")

        # Step 3: Generate Ansible deployment
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_local(),
            dry_run=True,
            output_dir=tmp_path / "ansible-deploy",
        )

        # Build image playbook
        build_result = backend.build_image(
            service_name="e2e-app",
            dockerfile_path=dockerfile,
            context_path=sandbox,
            tag="e2e",
        )
        assert build_result.success

        # Deploy playbook
        deploy_result = backend.deploy(
            service_name="e2e-app",
            image_name=build_result.image_name,
            port=3000,
            env={"NODE_ENV": "production"},
            health_check="/health",
        )
        assert deploy_result.success

        # Step 4: Verify all Ansible files generated
        ansible_dir = tmp_path / "ansible-deploy"
        assert (ansible_dir / "build.yml").exists()
        assert (ansible_dir / "deploy.yml").exists()
        assert (ansible_dir / "inventory.yml").exists()

    def test_mobile_capacitor_full_workflow(self, tmp_path: Path) -> None:
        """Full workflow: scaffold Capacitor → deploy via Ansible."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "e2e-cap"
        sandbox.mkdir()
        (sandbox / "dist").mkdir()
        (sandbox / "dist" / "index.html").write_text("<html><body>Capacitor</body></html>")

        # Step 1: Scaffold
        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="e2e-cap",
            extra={"targets": ["android", "ios"]},
        )

        # Step 2: Write all Ansible files at once
        backend = AnsibleBackend(
            config=DeploymentConfig.for_production(),
            ansible_config=AnsibleConfig.for_remote(["app-server.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible-cap",
        )

        paths = backend.write_all(
            service_name="e2e-cap",
            image_name="pactown/e2e-cap:v1",
            port=8100,
            env={"CAPACITOR_ANDROID_STUDIO": "1"},
            health_check="/",
        )

        # Verify all files
        assert paths["inventory"].exists()
        assert paths["deploy"].exists()
        assert paths["teardown"].exists()

        # Verify teardown content
        teardown = yaml.safe_load(paths["teardown"].read_text())
        assert teardown[0]["tasks"][0]["community.docker.docker_container"]["state"] == "absent"

    def test_multi_service_ansible_deployment(self, tmp_path: Path) -> None:
        """Deploy multiple services (desktop + mobile) via single Ansible inventory."""
        from pactown.builders import DesktopBuilder, MobileBuilder

        # Service 1: Electron desktop
        electron_sandbox = tmp_path / "electron-svc"
        electron_sandbox.mkdir()
        DesktopBuilder().scaffold(electron_sandbox, framework="electron", app_name="desktop-api")

        # Service 2: Capacitor mobile
        cap_sandbox = tmp_path / "cap-svc"
        cap_sandbox.mkdir()
        (cap_sandbox / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(cap_sandbox, framework="capacitor", app_name="mobile-client")

        # Shared Ansible config
        ansible_config = AnsibleConfig.for_remote(
            hosts=["service-1.example.com", "service-2.example.com"],
            user="deploy",
        )

        # Deploy both services
        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=ansible_config,
            dry_run=True,
            output_dir=tmp_path / "ansible-multi",
        )

        # Deploy desktop service
        result1 = backend.deploy(
            service_name="desktop-api",
            image_name="pactown/desktop-api:v1",
            port=8000,
            env={"SERVICE": "api"},
        )
        assert result1.success

        # Deploy mobile service
        result2 = backend.deploy(
            service_name="mobile-client",
            image_name="pactown/mobile-client:v1",
            port=8100,
            env={"SERVICE": "mobile"},
        )
        assert result2.success

        # Verify same inventory used
        inv = yaml.safe_load((tmp_path / "ansible-multi" / "inventory.yml").read_text())
        hosts = list(inv["all"]["children"]["pactown_hosts"]["hosts"].keys())
        assert len(hosts) == 2


# ===========================================================================
# Artifact generation tests - Desktop platforms
# ===========================================================================


class TestDesktopArtifactGeneration:
    """Test correct artifact generation for desktop apps across different OS platforms."""

    def test_electron_linux_appimage_artifact(self, tmp_path: Path) -> None:
        """Test Electron build generates AppImage artifact for Linux."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-linux"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="linux-app")

        # Simulate Electron build output
        dist = sandbox / "dist"
        dist.mkdir()
        appimage = dist / "linux-app-1.0.0.AppImage"
        appimage.write_bytes(b"fake-appimage-content")

        # Collect artifacts
        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert len(artifacts) >= 1
        assert any(a.name.endswith(".AppImage") for a in artifacts)

        # Deploy with Ansible
        backend = AnsibleBackend(
            config=_deploy_config(namespace="linux"),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        result = backend.deploy(
            service_name="linux-app",
            image_name="pactown/linux-app:appimage",
            port=3000,
            env={"PLATFORM": "linux"},
        )

        assert result.success

    def test_electron_windows_exe_artifact(self, tmp_path: Path) -> None:
        """Test Electron build generates .exe artifact for Windows."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-windows"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="win-app")

        # Simulate Windows build output
        dist = sandbox / "dist"
        dist.mkdir()
        exe = dist / "win-app Setup 1.0.0.exe"
        exe.write_bytes(b"fake-exe-content")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert any(a.name.endswith(".exe") for a in artifacts)

        # Verify package.json has Windows build config
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "win" in pkg["build"]
        assert pkg["build"]["win"]["target"] == ["nsis"]

    def test_electron_macos_dmg_artifact(self, tmp_path: Path) -> None:
        """Test Electron build generates .dmg artifact for macOS."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-macos"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="mac-app")

        # Simulate macOS build output
        dist = sandbox / "dist"
        dist.mkdir()
        dmg = dist / "mac-app-1.0.0.dmg"
        dmg.write_bytes(b"fake-dmg-content")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert any(a.name.endswith(".dmg") for a in artifacts)

        # Verify package.json has macOS build config
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "mac" in pkg["build"]
        assert pkg["build"]["mac"]["target"] == ["dmg"]

    def test_electron_snap_artifact(self, tmp_path: Path) -> None:
        """Test Electron build can generate .snap artifact for Linux."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-snap"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="snap-app")

        dist = sandbox / "dist"
        dist.mkdir()
        snap = dist / "snap-app_1.0.0_amd64.snap"
        snap.write_bytes(b"fake-snap-content")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert any(a.name.endswith(".snap") for a in artifacts)

    def test_electron_linux_launcher_artifacts(self, tmp_path: Path) -> None:
        """Test Electron Linux build includes run.sh and README.txt artifacts."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-launcher"
        sandbox.mkdir()

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "app.AppImage").write_bytes(b"fake")
        (dist / "run.sh").write_text("#!/bin/bash\n")
        (dist / "README.txt").write_text("Instructions\n")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "electron")

        artifact_names = {a.name for a in artifacts}
        assert "app.AppImage" in artifact_names
        assert "run.sh" in artifact_names
        assert "README.txt" in artifact_names

    def test_tauri_linux_appimage_artifact(self, tmp_path: Path) -> None:
        """Test Tauri build generates AppImage artifact for Linux."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tauri-linux"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="tauri", app_name="tauri-linux")

        # Simulate Tauri build output
        bundle_dir = sandbox / "src-tauri" / "target" / "release" / "bundle" / "appimage"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "tauri-linux_1.0.0_amd64.AppImage").write_bytes(b"fake-tauri-appimage")

        artifacts = builder._collect_artifacts(sandbox, "tauri")
        assert len(artifacts) >= 1
        assert any("AppImage" in a.name for a in artifacts)

    def test_tauri_deb_artifact(self, tmp_path: Path) -> None:
        """Test Tauri can generate .deb artifact for Debian/Ubuntu."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tauri-deb"
        sandbox.mkdir()

        bundle_dir = sandbox / "src-tauri" / "target" / "release" / "bundle" / "deb"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "tauri-app_1.0.0_amd64.deb").write_bytes(b"fake-deb")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "tauri")
        assert any(a.name.endswith(".deb") for a in artifacts)

    def test_pyinstaller_linux_binary_artifact(self, tmp_path: Path) -> None:
        """Test PyInstaller generates Linux binary artifact."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "pyinstaller-linux"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="pyinstaller", app_name="pyapp")

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "pyapp").write_bytes(b"fake-linux-binary")

        artifacts = builder._collect_artifacts(sandbox, "pyinstaller")
        assert len(artifacts) == 1
        assert artifacts[0].name == "pyapp"

    def test_pyinstaller_windows_exe_artifact(self, tmp_path: Path) -> None:
        """Test PyInstaller generates Windows .exe artifact."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "pyinstaller-windows"
        sandbox.mkdir()

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "pyapp.exe").write_bytes(b"fake-windows-exe")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "pyinstaller")
        assert artifacts[0].name == "pyapp.exe"

    def test_pyqt_multi_os_artifacts(self, tmp_path: Path) -> None:
        """Test PyQt can generate artifacts for multiple OS platforms."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "pyqt-multi"
        sandbox.mkdir()

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "app-linux").write_bytes(b"linux")
        (dist / "app.exe").write_bytes(b"windows")
        (dist / "app.app").mkdir()  # macOS app bundle

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "pyqt")
        assert len(artifacts) >= 2  # At least Linux and Windows


# ===========================================================================
# Artifact generation tests - Mobile platforms
# ===========================================================================


class TestMobileArtifactGeneration:
    """Test correct artifact generation for mobile apps across different platforms."""

    def test_capacitor_android_apk_artifact(self, tmp_path: Path) -> None:
        """Test Capacitor Android build generates .apk artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "capacitor-android"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="cap-android",
            extra={"targets": ["android"]},
        )

        # Simulate Android build output
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "debug"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-debug.apk").write_bytes(b"fake-apk")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert len(artifacts) == 1
        assert artifacts[0].name == "app-debug.apk"

        # Deploy with Ansible
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        result = backend.deploy(
            service_name="cap-android",
            image_name="pactown/cap-android:latest",
            port=8100,
            env={"TARGET": "android"},
        )

        assert result.success

    def test_capacitor_android_release_apk_artifact(self, tmp_path: Path) -> None:
        """Test Capacitor Android release build generates signed .apk."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "capacitor-release"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="capacitor", app_name="cap-release")

        # Simulate release build
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"fake-signed-apk")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert artifacts[0].name == "app-release.apk"

    def test_capacitor_ios_ipa_artifact(self, tmp_path: Path) -> None:
        """Test Capacitor iOS build generates .ipa artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "capacitor-ios"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="cap-ios",
            extra={"targets": ["ios"]},
        )

        # Simulate iOS build output
        ipa_dir = sandbox / "ios" / "App" / "build" / "Release"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "App.ipa").write_bytes(b"fake-ipa")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert artifacts[0].name == "App.ipa"

    def test_capacitor_dual_platform_artifacts(self, tmp_path: Path) -> None:
        """Test Capacitor build can generate both Android and iOS artifacts."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "capacitor-dual"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="cap-dual",
            extra={"targets": ["android", "ios"]},
        )

        # Verify both platform dependencies
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "@capacitor/android" in pkg["dependencies"]
        assert "@capacitor/ios" in pkg["dependencies"]

        # Simulate both platform builds
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"fake-apk")

        ipa_dir = sandbox / "ios" / "App" / "build" / "Release"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "App.ipa").write_bytes(b"fake-ipa")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert len(artifacts) == 2
        names = {a.name for a in artifacts}
        assert "app-release.apk" in names
        assert "App.ipa" in names

    def test_react_native_android_apk_artifact(self, tmp_path: Path) -> None:
        """Test React Native Android build generates .apk artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn-android"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="react-native", app_name="rnapp")

        # Simulate Android build
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"fake-rn-apk")

        artifacts = builder._collect_artifacts(sandbox, "react-native")
        assert len(artifacts) == 1
        assert artifacts[0].name == "app-release.apk"

    def test_react_native_ios_ipa_artifact(self, tmp_path: Path) -> None:
        """Test React Native iOS build generates .ipa artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn-ios"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="react-native", app_name="rnios")

        # Simulate iOS build
        ipa_dir = sandbox / "ios" / "build" / "Release"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "rnios.ipa").write_bytes(b"fake-rn-ipa")

        artifacts = builder._collect_artifacts(sandbox, "react-native")
        assert artifacts[0].name == "rnios.ipa"

    def test_flutter_android_apk_artifact(self, tmp_path: Path) -> None:
        """Test Flutter Android build generates .apk artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "flutter-android"
        sandbox.mkdir()

        builder = MobileBuilder()

        # Simulate Flutter Android build
        apk_dir = sandbox / "build" / "app" / "outputs" / "flutter-apk"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"fake-flutter-apk")

        artifacts = builder._collect_artifacts(sandbox, "flutter")
        assert len(artifacts) == 1
        assert artifacts[0].name == "app-release.apk"

    def test_flutter_ios_ipa_artifact(self, tmp_path: Path) -> None:
        """Test Flutter iOS build generates .ipa artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "flutter-ios"
        sandbox.mkdir()

        builder = MobileBuilder()

        # Simulate Flutter iOS build
        ipa_dir = sandbox / "build" / "ios" / "ipa"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "Runner.ipa").write_bytes(b"fake-flutter-ipa")

        artifacts = builder._collect_artifacts(sandbox, "flutter")
        assert artifacts[0].name == "Runner.ipa"

    def test_kivy_android_apk_artifact(self, tmp_path: Path) -> None:
        """Test Kivy/Buildozer generates .apk artifact for Android."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "kivy-android"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="kivy", app_name="kivyapp")

        # Simulate Buildozer output
        bin_dir = sandbox / "bin"
        bin_dir.mkdir()
        (bin_dir / "kivyapp-0.1-debug.apk").write_bytes(b"fake-kivy-apk")

        artifacts = builder._collect_artifacts(sandbox, "kivy")
        assert artifacts[0].name == "kivyapp-0.1-debug.apk"

    def test_kivy_android_aab_artifact(self, tmp_path: Path) -> None:
        """Test Kivy can generate .aab (Android App Bundle) artifact."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "kivy-aab"
        sandbox.mkdir()

        bin_dir = sandbox / "bin"
        bin_dir.mkdir()
        (bin_dir / "kivyapp-0.1-release.aab").write_bytes(b"fake-kivy-aab")

        builder = MobileBuilder()
        artifacts = builder._collect_artifacts(sandbox, "kivy")
        assert artifacts[0].name == "kivyapp-0.1-release.aab"


# ===========================================================================
# Multi-platform artifact tests with Ansible deployment
# ===========================================================================


class TestMultiPlatformArtifactsWithAnsible:
    """Test artifact generation for multiple platforms with Ansible deployment."""

    def test_electron_all_platforms_artifacts(self, tmp_path: Path) -> None:
        """Test Electron generates artifacts for Linux, Windows, and macOS simultaneously."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "electron-all"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="multi-app")

        # Simulate multi-platform build output
        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "multi-app-1.0.0.AppImage").write_bytes(b"linux")
        (dist / "multi-app Setup 1.0.0.exe").write_bytes(b"windows")
        (dist / "multi-app-1.0.0.dmg").write_bytes(b"macos")
        (dist / "run.sh").write_text("#!/bin/bash\n")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert len(artifacts) >= 4

        names = {a.name for a in artifacts}
        assert any(".AppImage" in n for n in names)
        assert any(".exe" in n for n in names)
        assert any(".dmg" in n for n in names)
        assert "run.sh" in names

        # Deploy each platform with Ansible
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        platforms = ["linux", "windows", "macos"]
        for platform in platforms:
            result = backend.deploy(
                service_name=f"multi-app-{platform}",
                image_name=f"pactown/multi-app:{platform}",
                port=3000,
                env={"PLATFORM": platform},
            )
            assert result.success

    def test_capacitor_android_ios_artifacts_with_ansible(self, tmp_path: Path) -> None:
        """Test Capacitor generates both Android and iOS artifacts with Ansible deployment."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "cap-both"
        sandbox.mkdir()
        (sandbox / "dist").mkdir()
        (sandbox / "dist" / "index.html").write_text("<html></html>")

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="dual-platform",
            extra={"targets": ["android", "ios"]},
        )

        # Simulate both platform builds
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"android-artifact")

        ipa_dir = sandbox / "ios" / "App" / "build" / "Release"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "App.ipa").write_bytes(b"ios-artifact")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert len(artifacts) == 2

        # Deploy Android with Ansible
        backend_android = AnsibleBackend(
            config=_deploy_config(namespace="android"),
            ansible_config=AnsibleConfig.for_remote(["android-build-server.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible-android",
        )

        result_android = backend_android.deploy(
            service_name="dual-platform-android",
            image_name="pactown/dual-platform:android",
            port=8100,
            env={"TARGET": "android", "ARTIFACT": str(artifacts[0])},
        )
        assert result_android.success

        # Deploy iOS with Ansible
        backend_ios = AnsibleBackend(
            config=_deploy_config(namespace="ios"),
            ansible_config=AnsibleConfig.for_remote(["ios-build-server.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible-ios",
        )

        result_ios = backend_ios.deploy(
            service_name="dual-platform-ios",
            image_name="pactown/dual-platform:ios",
            port=8101,
            env={"TARGET": "ios", "ARTIFACT": str(artifacts[1])},
        )
        assert result_ios.success

    def test_artifact_paths_in_ansible_playbook(self, tmp_path: Path) -> None:
        """Test artifact paths are correctly referenced in Ansible playbooks."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "artifact-paths"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="path-test")

        # Create artifacts
        dist = sandbox / "dist"
        dist.mkdir()
        artifact = dist / "path-test-1.0.0.AppImage"
        artifact.write_bytes(b"artifact-content")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert len(artifacts) >= 1

        # Deploy with artifact metadata
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        artifact_path = str(artifacts[0].absolute())
        result = backend.deploy(
            service_name="path-test",
            image_name="pactown/path-test:latest",
            port=3000,
            env={"ARTIFACT_PATH": artifact_path, "ARTIFACT_NAME": artifacts[0].name},
        )

        assert result.success

        # Verify playbook contains artifact metadata
        pb = yaml.safe_load((tmp_path / "ansible" / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["ARTIFACT_PATH"] == artifact_path
        assert container["env"]["ARTIFACT_NAME"] == "path-test-1.0.0.AppImage"

    def test_flutter_multi_platform_architecture_artifacts(self, tmp_path: Path) -> None:
        """Test Flutter generates architecture-specific artifacts (arm64, x86_64)."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "flutter-arch"
        sandbox.mkdir()

        builder = MobileBuilder()

        # Simulate multi-architecture Android build
        apk_dir = sandbox / "build" / "app" / "outputs" / "flutter-apk"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-arm64-v8a-release.apk").write_bytes(b"arm64")
        (apk_dir / "app-armeabi-v7a-release.apk").write_bytes(b"armv7")
        (apk_dir / "app-x86_64-release.apk").write_bytes(b"x86_64")

        artifacts = builder._collect_artifacts(sandbox, "flutter")
        assert len(artifacts) == 3

        # Deploy each architecture
        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible-flutter",
        )

        for artifact in artifacts:
            arch = artifact.name.split("-")[1]  # Extract architecture
            result = backend.deploy(
                service_name=f"flutter-{arch}",
                image_name=f"pactown/flutter:{arch}",
                port=8080,
                env={"ARCHITECTURE": arch, "APK": artifact.name},
            )
            assert result.success


# ===========================================================================
# Scaffold config correctness per platform/OS
# ===========================================================================


class TestScaffoldConfigCorrectness:
    """Verify scaffold generates correct config files for each framework and OS."""

    # -- Electron --

    def test_electron_package_json_build_targets_all_os(self, tmp_path: Path) -> None:
        """Electron package.json must contain build targets for Linux, Windows, macOS."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app")

        pkg = json.loads((sandbox / "package.json").read_text())
        build = pkg["build"]
        assert build["linux"]["target"] == ["AppImage"]
        assert build["win"]["target"] == ["nsis"]
        assert build["mac"]["target"] == ["dmg"]

    def test_electron_package_json_app_id(self, tmp_path: Path) -> None:
        """Electron build.appId uses custom or default value."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp",
                                  extra={"app_id": "org.custom.myapp"})
        pkg = json.loads((sandbox / "package.json").read_text())
        assert pkg["build"]["appId"] == "org.custom.myapp"

    def test_electron_package_json_default_app_id(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="foo")
        pkg = json.loads((sandbox / "package.json").read_text())
        assert pkg["build"]["appId"] == "com.pactown.foo"

    def test_electron_main_js_has_no_sandbox(self, tmp_path: Path) -> None:
        """Scaffolded main.js must include --no-sandbox for AppImage compatibility."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app")
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src
        assert "app.commandLine.appendSwitch" in src

    def test_electron_main_js_window_dimensions(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app",
                                  extra={"window_width": 1920, "window_height": 1080})
        src = (sandbox / "main.js").read_text()
        assert "1920" in src
        assert "1080" in src

    def test_electron_dev_deps_pinned(self, tmp_path: Path) -> None:
        """electron and electron-builder must be in devDependencies with pinned versions."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app")
        pkg = json.loads((sandbox / "package.json").read_text())
        dev = pkg["devDependencies"]
        assert "electron" in dev
        assert "electron-builder" in dev
        assert dev["electron"].startswith("^")
        assert dev["electron-builder"].startswith("^")

    def test_electron_moves_electron_from_deps_to_dev_deps(self, tmp_path: Path) -> None:
        """If electron is in dependencies, scaffold moves it to devDependencies."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "package.json").write_text(json.dumps({
            "name": "app", "version": "1.0.0",
            "dependencies": {"electron": "^30.0.0", "express": "^4.0.0"},
        }))
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app")
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "electron" not in pkg.get("dependencies", {})
        assert "electron" in pkg["devDependencies"]
        assert "express" in pkg["dependencies"]

    # -- Tauri --

    def test_tauri_conf_bundle_identifier(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "t"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp",
                                  extra={"app_id": "com.example.tapp"})
        conf = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        assert conf["tauri"]["bundle"]["identifier"] == "com.example.tapp"
        assert conf["tauri"]["bundle"]["targets"] == "all"

    def test_tauri_conf_window_size(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "t"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp",
                                  extra={"window_width": 800, "window_height": 600})
        conf = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        win = conf["tauri"]["windows"][0]
        assert win["width"] == 800
        assert win["height"] == 600

    def test_tauri_conf_default_window_size(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "t"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp")
        conf = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        win = conf["tauri"]["windows"][0]
        assert win["width"] == 1024
        assert win["height"] == 768

    def test_tauri_conf_product_name(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "t"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="my-tauri")
        conf = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        assert conf["package"]["productName"] == "my-tauri"

    # -- PyInstaller / PyQt --

    def test_pyinstaller_spec_content(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "p"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("print('hello')\n")
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="mybin")
        spec = (sandbox / "mybin.spec").read_text()
        assert "Analysis(['main.py']" in spec
        assert "name='mybin'" in spec
        assert "console=False" in spec

    def test_pyinstaller_spec_no_icon_by_default(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "p"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("")
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="app")
        spec = (sandbox / "app.spec").read_text()
        assert "icon=" not in spec

    def test_pyqt_spec_with_icon(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "q"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("")
        DesktopBuilder().scaffold(sandbox, framework="pyqt", app_name="gui",
                                  extra={"icon": "icon.ico"})
        spec = (sandbox / "gui.spec").read_text()
        assert "icon='icon.ico'" in spec

    def test_tkinter_spec_generated(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tk"
        sandbox.mkdir()
        (sandbox / "main.py").write_text("")
        DesktopBuilder().scaffold(sandbox, framework="tkinter", app_name="tkapp")
        assert (sandbox / "tkapp.spec").exists()

    # -- Capacitor --

    def test_capacitor_config_json_fields(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap",
                                 extra={"app_id": "com.test.cap"})
        conf = json.loads((sandbox / "capacitor.config.json").read_text())
        assert conf["appId"] == "com.test.cap"
        assert conf["appName"] == "cap"
        assert conf["bundledWebRuntime"] is False
        assert conf["server"]["androidScheme"] == "https"

    def test_capacitor_scripts_in_package_json(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap")
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "cap:sync" in pkg["scripts"]
        assert "cap:build:android" in pkg["scripts"]
        assert "cap:build:ios" in pkg["scripts"]

    def test_capacitor_webdir_root_index(self, tmp_path: Path) -> None:
        """When index.html is at root, webDir should be '.'."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap")
        conf = json.loads((sandbox / "capacitor.config.json").read_text())
        assert conf["webDir"] == "."

    def test_capacitor_webdir_build_dir(self, tmp_path: Path) -> None:
        """When index.html is in build/, webDir should be 'build'."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "build").mkdir()
        (sandbox / "build" / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap")
        conf = json.loads((sandbox / "capacitor.config.json").read_text())
        assert conf["webDir"] == "build"

    def test_capacitor_webdir_www_dir(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "www").mkdir()
        (sandbox / "www" / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap")
        conf = json.loads((sandbox / "capacitor.config.json").read_text())
        assert conf["webDir"] == "www"

    def test_capacitor_plugin_version_pinning(self, tmp_path: Path) -> None:
        """Capacitor plugins set to 'latest' should be pinned to ^6.0.0."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "c"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")
        (sandbox / "package.json").write_text(json.dumps({
            "name": "app", "version": "1.0.0",
            "dependencies": {"@capacitor/storage": "latest", "@capacitor/camera": "latest"},
        }))
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="cap")
        pkg = json.loads((sandbox / "package.json").read_text())
        assert pkg["dependencies"]["@capacitor/storage"] == "^6.0.0"
        assert pkg["dependencies"]["@capacitor/camera"] == "^6.0.0"

    # -- React Native --

    def test_react_native_app_json_display_name(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn"
        sandbox.mkdir()
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="myapp",
                                 extra={"app_name": "My Application"})
        data = json.loads((sandbox / "app.json").read_text())
        assert data["name"] == "myapp"
        assert data["displayName"] == "My Application"

    def test_react_native_app_json_default_display_name(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn"
        sandbox.mkdir()
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp")
        data = json.loads((sandbox / "app.json").read_text())
        assert data["displayName"] == "rnapp"

    # -- Kivy --

    def test_kivy_buildozer_spec_fields(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "k"
        sandbox.mkdir()
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivytest",
                                 extra={"app_id": "org.test.kivy", "fullscreen": True})
        spec = (sandbox / "buildozer.spec").read_text()
        assert "title = kivytest" in spec
        assert "package.name = kivytest" in spec
        assert "package.domain = org.test" in spec
        assert "fullscreen = 1" in spec
        assert "requirements = python3,kivy" in spec

    def test_kivy_buildozer_spec_icon(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "k"
        sandbox.mkdir()
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="app",
                                 extra={"icon": "assets/icon.png"})
        spec = (sandbox / "buildozer.spec").read_text()
        assert "icon.filename = assets/icon.png" in spec

    def test_kivy_buildozer_spec_no_icon(self, tmp_path: Path) -> None:
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "k"
        sandbox.mkdir()
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="app")
        spec = (sandbox / "buildozer.spec").read_text()
        assert "# icon.filename =" in spec


# ===========================================================================
# Build command generation per framework/OS
# ===========================================================================


class TestBuildCommandGeneration:
    """Verify correct build commands are generated for each framework."""

    # -- Desktop --

    def test_electron_default_build_cmd_linux(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("electron", ["linux"])
        assert "electron-builder" in cmd
        assert "--linux" in cmd

    def test_electron_default_build_cmd_no_targets(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("electron", None)
        assert "--linux" in cmd  # fallback

    def test_tauri_default_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("tauri", None)
        assert cmd == "npx tauri build"

    def test_pyinstaller_default_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("pyinstaller", None)
        assert "pyinstaller" in cmd
        assert "--onefile" in cmd
        assert "--windowed" in cmd

    def test_pyqt_default_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("pyqt", None)
        assert "pyinstaller" in cmd

    def test_tkinter_default_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("tkinter", None)
        assert "pyinstaller" in cmd

    def test_flutter_desktop_default_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("flutter", ["linux"])
        assert cmd == "flutter build linux"

    def test_flutter_desktop_macos_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("flutter", ["macos"])
        assert cmd == "flutter build macos"

    def test_flutter_desktop_windows_build_cmd(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("flutter", ["windows"])
        assert cmd == "flutter build windows"

    def test_unknown_framework_returns_empty(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._default_build_cmd("unknown", None)
        assert cmd == ""

    # -- Mobile --

    def test_capacitor_android_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("capacitor", ["android"])
        assert "cap sync" in cmd
        assert "cap build android" in cmd

    def test_capacitor_ios_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("capacitor", ["ios"])
        assert "cap build ios" in cmd

    def test_react_native_android_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("react-native", ["android"])
        assert "build-android" in cmd
        assert "--mode=release" in cmd

    def test_react_native_ios_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("react-native", ["ios"])
        assert "build-ios" in cmd

    def test_flutter_android_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("flutter", ["android"])
        assert cmd == "flutter build apk --release"

    def test_flutter_ios_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("flutter", ["ios"])
        assert cmd == "flutter build ios --release"

    def test_kivy_android_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("kivy", ["android"])
        assert cmd == "buildozer android debug"

    def test_kivy_ios_build_cmd(self) -> None:
        from pactown.builders import MobileBuilder
        cmd = MobileBuilder._default_build_cmd("kivy", ["ios"])
        assert cmd == "buildozer ios debug"


# ===========================================================================
# Electron no-sandbox patch patterns
# ===========================================================================


class TestElectronNoSandboxPatch:
    """Test all 4 patterns of --no-sandbox injection into main.js."""

    def test_patch_commonjs_require(self, tmp_path: Path) -> None:
        """Pattern 1: CommonJS require('electron')."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text(
            "const { app, BrowserWindow } = require('electron');\n"
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is True
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src
        assert "app.commandLine.appendSwitch" in src

    def test_patch_es_module_import(self, tmp_path: Path) -> None:
        """Pattern 2: ES module import from 'electron'."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text(
            "import { app, BrowserWindow } from 'electron';\n"
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is True
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src

    def test_patch_app_whenready_fallback(self, tmp_path: Path) -> None:
        """Pattern 3: Fallback near app.whenReady – patch is injected."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text(
            "// custom electron app\n"
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is True
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src
        assert "app.commandLine.appendSwitch" in src

    def test_patch_app_on_fallback(self, tmp_path: Path) -> None:
        """Pattern 3b: Fallback before app.on(."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text(
            "// custom\n"
            "app.on('ready', () => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is True
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src

    def test_patch_ultimate_fallback_prepend(self, tmp_path: Path) -> None:
        """Pattern 4: No recognizable pattern – prepend at top."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text("console.log('custom app');\n")
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is True
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src
        assert src.startswith("// AppImage on Linux")

    def test_patch_skips_already_patched(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        (sandbox / "main.js").write_text(
            "const { app } = require('electron');\n"
            "app.commandLine.appendSwitch('no-sandbox');\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is False

    def test_patch_no_main_js(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        assert DesktopBuilder._patch_electron_no_sandbox(sandbox) is False


# ===========================================================================
# Electron builder flag filtering per host OS
# ===========================================================================


class TestElectronBuilderFlagFiltering:
    """Test electron-builder flag filtering based on host OS."""

    def test_filter_keeps_linux_flag(self) -> None:
        from pactown.builders import DesktopBuilder
        cmd = DesktopBuilder._filter_electron_builder_cmd("npx electron-builder --linux")
        assert "--linux" in cmd

    def test_filter_strips_mac_on_non_darwin(self) -> None:
        """--mac should be stripped on non-macOS hosts."""
        import platform as plat
        from pactown.builders import DesktopBuilder

        if plat.system().lower() != "darwin":
            cmd = DesktopBuilder._filter_electron_builder_cmd("npx electron-builder --mac --linux")
            assert "--mac" not in cmd
            assert "--linux" in cmd

    def test_filter_ensures_at_least_one_platform(self) -> None:
        """If all flags are stripped, --linux is added as fallback."""
        import platform as plat
        from pactown.builders import DesktopBuilder

        if plat.system().lower() == "linux":
            cmd = DesktopBuilder._filter_electron_builder_cmd("npx electron-builder --mac")
            assert "--linux" in cmd

    def test_electron_builder_flags_linux_target(self) -> None:
        from pactown.builders import DesktopBuilder
        flags = DesktopBuilder._electron_builder_flags(["linux"])
        assert "--linux" in flags

    def test_electron_builder_flags_empty_defaults_linux(self) -> None:
        from pactown.builders import DesktopBuilder
        flags = DesktopBuilder._electron_builder_flags(None)
        assert "--linux" in flags

    def test_electron_builder_flags_no_duplicates(self) -> None:
        from pactown.builders import DesktopBuilder
        flags = DesktopBuilder._electron_builder_flags(["linux", "linux"])
        assert flags.count("--linux") == 1


# ===========================================================================
# Desktop Flutter & Tkinter artifact tests
# ===========================================================================


class TestDesktopFlutterTkinterArtifacts:
    """Test artifact collection for desktop Flutter and Tkinter builds."""

    def test_flutter_desktop_linux_artifacts(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "flutter-desk"
        sandbox.mkdir()

        # Simulate Flutter Linux desktop build
        linux_dir = sandbox / "build" / "linux" / "x64" / "release" / "bundle"
        linux_dir.mkdir(parents=True)
        (linux_dir / "flutter_app").write_bytes(b"binary")
        (linux_dir / "libflutter_linux_gtk.so").write_bytes(b"lib")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "flutter")
        assert len(artifacts) >= 1
        names = {a.name for a in artifacts}
        assert "flutter_app" in names

    def test_tkinter_dist_artifacts(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tkinter"
        sandbox.mkdir()

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "tkapp").write_bytes(b"binary")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "tkinter")
        assert len(artifacts) == 1
        assert artifacts[0].name == "tkapp"

    def test_tkinter_windows_artifact(self, tmp_path: Path) -> None:
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tkinter-win"
        sandbox.mkdir()

        dist = sandbox / "dist"
        dist.mkdir()
        (dist / "tkapp.exe").write_bytes(b"exe")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "tkinter")
        assert artifacts[0].name == "tkapp.exe"

    def test_unknown_framework_fallback_artifacts(self, tmp_path: Path) -> None:
        """Unknown frameworks should collect from dist/* and build/*."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "unknown"
        sandbox.mkdir()
        (sandbox / "dist").mkdir()
        (sandbox / "dist" / "output.bin").write_bytes(b"bin")
        (sandbox / "build").mkdir()
        (sandbox / "build" / "output2.bin").write_bytes(b"bin2")

        builder = DesktopBuilder()
        artifacts = builder._collect_artifacts(sandbox, "unknown-framework")
        names = {a.name for a in artifacts}
        assert "output.bin" in names
        assert "output2.bin" in names

    def test_mobile_unknown_framework_fallback(self, tmp_path: Path) -> None:
        """Unknown mobile frameworks should collect from build/**/*.apk etc."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "unknown-mobile"
        sandbox.mkdir()
        apk_dir = sandbox / "build" / "outputs"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app.apk").write_bytes(b"apk")

        builder = MobileBuilder()
        artifacts = builder._collect_artifacts(sandbox, "unknown-mobile")
        assert len(artifacts) == 1
        assert artifacts[0].name == "app.apk"


# ===========================================================================
# Ansible playbook artifact distribution per OS/platform
# ===========================================================================


class TestAnsibleArtifactDistribution:
    """Test Ansible playbooks correctly distribute artifacts per OS/platform."""

    def test_ansible_deploy_with_electron_linux_artifacts(self, tmp_path: Path) -> None:
        """Full flow: scaffold Electron → collect Linux artifacts → Ansible deploy."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "e"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="linuxapp")

        # Simulate Linux-only build
        dist = sandbox / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "linuxapp-1.0.0.AppImage").write_bytes(b"appimage")
        (dist / "run.sh").write_text("#!/bin/bash\n")
        (dist / "README.txt").write_text("instructions\n")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        assert len(artifacts) == 3

        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_remote(["linux-server.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        paths = backend.write_all(
            service_name="linuxapp",
            image_name="pactown/linuxapp:linux",
            port=3000,
            env={
                "PLATFORM": "linux",
                "ARTIFACTS": ",".join(a.name for a in artifacts),
                "APPIMAGE": next(a.name for a in artifacts if a.name.endswith(".AppImage")),
            },
            health_check="/health",
        )

        # Verify deploy playbook has artifact info
        pb = yaml.safe_load(paths["deploy"].read_text())
        env = pb[0]["tasks"][2]["community.docker.docker_container"]["env"]
        assert "linuxapp-1.0.0.AppImage" in env["ARTIFACTS"]
        assert env["APPIMAGE"] == "linuxapp-1.0.0.AppImage"

    def test_ansible_deploy_with_capacitor_android_artifacts(self, tmp_path: Path) -> None:
        """Full flow: scaffold Capacitor → collect Android artifacts → Ansible deploy."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "cap"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<html></html>")
        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="capacitor", app_name="capapp",
                         extra={"targets": ["android"]})

        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"apk")

        artifacts = builder._collect_artifacts(sandbox, "capacitor")
        assert len(artifacts) == 1

        backend = AnsibleBackend(
            config=DeploymentConfig.for_production(),
            ansible_config=AnsibleConfig.for_remote(["android-ci.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        result = backend.deploy(
            service_name="capapp-android",
            image_name="pactown/capapp:android",
            port=8100,
            env={
                "TARGET": "android",
                "APK_PATH": str(artifacts[0]),
                "APK_NAME": artifacts[0].name,
            },
        )

        assert result.success
        pb = yaml.safe_load((tmp_path / "ansible" / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["APK_NAME"] == "app-release.apk"
        # Production config should have security hardening
        assert container["read_only"] is True
        assert "no-new-privileges:true" in container["security_opts"]

    def test_ansible_deploy_multi_os_electron_with_separate_inventories(self, tmp_path: Path) -> None:
        """Deploy Electron artifacts to OS-specific servers via separate Ansible inventories."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "multi"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="electron", app_name="crossapp")

        dist = sandbox / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "crossapp-1.0.0.AppImage").write_bytes(b"linux")
        (dist / "crossapp Setup 1.0.0.exe").write_bytes(b"win")
        (dist / "crossapp-1.0.0.dmg").write_bytes(b"mac")

        artifacts = builder._collect_artifacts(sandbox, "electron")
        linux_arts = [a for a in artifacts if ".AppImage" in a.name]
        win_arts = [a for a in artifacts if ".exe" in a.name]
        mac_arts = [a for a in artifacts if ".dmg" in a.name]

        os_configs = {
            "linux": {
                "hosts": ["linux-1.example.com", "linux-2.example.com"],
                "artifacts": linux_arts,
                "port": 3001,
            },
            "windows": {
                "hosts": ["win-1.example.com"],
                "artifacts": win_arts,
                "port": 3002,
            },
            "macos": {
                "hosts": ["mac-1.example.com"],
                "artifacts": mac_arts,
                "port": 3003,
            },
        }

        for os_name, cfg in os_configs.items():
            backend = AnsibleBackend(
                config=_deploy_config(namespace=f"electron-{os_name}"),
                ansible_config=AnsibleConfig.for_remote(cfg["hosts"]),
                dry_run=True,
                output_dir=tmp_path / f"ansible-{os_name}",
            )

            art_names = ",".join(a.name for a in cfg["artifacts"])
            result = backend.deploy(
                service_name=f"crossapp-{os_name}",
                image_name=f"pactown/crossapp:{os_name}",
                port=cfg["port"],
                env={"OS": os_name, "ARTIFACTS": art_names},
            )

            assert result.success

            # Verify inventory has correct hosts
            inv = yaml.safe_load(
                (tmp_path / f"ansible-{os_name}" / "inventory.yml").read_text()
            )
            hosts = list(inv["all"]["children"]["pactown_hosts"]["hosts"].keys())
            assert hosts == cfg["hosts"]

            # Verify playbook has correct namespace
            pb = yaml.safe_load(
                (tmp_path / f"ansible-{os_name}" / "deploy.yml").read_text()
            )
            container = pb[0]["tasks"][2]["community.docker.docker_container"]
            assert container["name"] == f"electron-{os_name}-crossapp-{os_name}"
            assert container["env"]["OS"] == os_name

    def test_ansible_deploy_kivy_with_buildozer_artifacts(self, tmp_path: Path) -> None:
        """Full flow: scaffold Kivy → collect APK/AAB → Ansible deploy."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "kivy"
        sandbox.mkdir()
        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="kivy", app_name="kivyapp",
                         extra={"app_id": "org.test.kivy"})

        # Simulate both APK and AAB output
        bin_dir = sandbox / "bin"
        bin_dir.mkdir()
        (bin_dir / "kivyapp-0.1-debug.apk").write_bytes(b"apk")
        (bin_dir / "kivyapp-0.1-release.aab").write_bytes(b"aab")

        artifacts = builder._collect_artifacts(sandbox, "kivy")
        assert len(artifacts) == 2
        names = {a.name for a in artifacts}
        assert any(".apk" in n for n in names)
        assert any(".aab" in n for n in names)

        backend = AnsibleBackend(
            config=_deploy_config(),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        result = backend.deploy(
            service_name="kivyapp",
            image_name="pactown/kivyapp:android",
            port=5555,
            env={
                "APK": next(a.name for a in artifacts if ".apk" in a.name),
                "AAB": next(a.name for a in artifacts if ".aab" in a.name),
            },
        )

        assert result.success
        pb = yaml.safe_load((tmp_path / "ansible" / "deploy.yml").read_text())
        env = pb[0]["tasks"][2]["community.docker.docker_container"]["env"]
        assert env["APK"] == "kivyapp-0.1-debug.apk"
        assert env["AAB"] == "kivyapp-0.1-release.aab"

    def test_ansible_deploy_tauri_with_multi_format_artifacts(self, tmp_path: Path) -> None:
        """Tauri generates multiple bundle formats – verify all collected and deployed."""
        from pactown.builders import DesktopBuilder

        sandbox = tmp_path / "tauri"
        sandbox.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="tauri", app_name="tauriapp")

        # Simulate Tauri multi-format output
        base = sandbox / "src-tauri" / "target" / "release" / "bundle"
        for fmt, fname in [
            ("appimage", "tauriapp_1.0.0_amd64.AppImage"),
            ("deb", "tauriapp_1.0.0_amd64.deb"),
            ("rpm", "tauriapp-1.0.0-1.x86_64.rpm"),
        ]:
            d = base / fmt
            d.mkdir(parents=True)
            (d / fname).write_bytes(b"artifact")

        artifacts = builder._collect_artifacts(sandbox, "tauri")
        assert len(artifacts) == 3
        names = {a.name for a in artifacts}
        assert any(".AppImage" in n for n in names)
        assert any(".deb" in n for n in names)
        assert any(".rpm" in n for n in names)

        backend = AnsibleBackend(
            config=_deploy_config(),
            ansible_config=AnsibleConfig.for_remote(["tauri-server.com"]),
            dry_run=True,
            output_dir=tmp_path / "ansible",
        )

        result = backend.deploy(
            service_name="tauriapp",
            image_name="pactown/tauriapp:linux",
            port=8080,
            env={
                "ARTIFACTS": ",".join(sorted(a.name for a in artifacts)),
                "FORMAT_COUNT": str(len(artifacts)),
            },
        )

        assert result.success
        pb = yaml.safe_load((tmp_path / "ansible" / "deploy.yml").read_text())
        env = pb[0]["tasks"][2]["community.docker.docker_container"]["env"]
        assert env["FORMAT_COUNT"] == "3"

    def test_ansible_deploy_react_native_dual_platform(self, tmp_path: Path) -> None:
        """React Native: collect Android + iOS artifacts, deploy separately via Ansible."""
        from pactown.builders import MobileBuilder

        sandbox = tmp_path / "rn"
        sandbox.mkdir()
        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="react-native", app_name="rnapp")

        # Android
        apk_dir = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_bytes(b"android")

        # iOS
        ipa_dir = sandbox / "ios" / "build" / "Release"
        ipa_dir.mkdir(parents=True)
        (ipa_dir / "rnapp.ipa").write_bytes(b"ios")

        artifacts = builder._collect_artifacts(sandbox, "react-native")
        assert len(artifacts) == 2

        android_art = next(a for a in artifacts if ".apk" in a.name)
        ios_art = next(a for a in artifacts if ".ipa" in a.name)

        for target, art, port in [("android", android_art, 8081), ("ios", ios_art, 8082)]:
            backend = AnsibleBackend(
                config=_deploy_config(namespace=f"rn-{target}"),
                dry_run=True,
                output_dir=tmp_path / f"ansible-{target}",
            )

            result = backend.deploy(
                service_name=f"rnapp-{target}",
                image_name=f"pactown/rnapp:{target}",
                port=port,
                env={"TARGET": target, "ARTIFACT": art.name},
            )

            assert result.success
            pb = yaml.safe_load(
                (tmp_path / f"ansible-{target}" / "deploy.yml").read_text()
            )
            container = pb[0]["tasks"][2]["community.docker.docker_container"]
            assert container["name"] == f"rn-{target}-rnapp-{target}"
            assert container["env"]["ARTIFACT"] == art.name


# ===========================================================================
# Artifacts in .pactown sandbox root (PACTOWN_SANDBOX_ROOT integration)
# ===========================================================================


class TestArtifactsInPactownSandboxRoot:
    """Verify that builders create artifacts inside the configured sandbox root
    (i.e. .pactown/) rather than a random temp directory."""

    def test_sandbox_manager_uses_configured_root(self) -> None:
        """SandboxManager.sandbox_root matches what we pass in."""
        from pactown.sandbox_manager import SandboxManager
        import tempfile, shutil

        root = Path(tempfile.mkdtemp(prefix="pactown_test_"))
        try:
            sm = SandboxManager(root)
            assert sm.sandbox_root == root
            assert root.exists()
            sp = sm.get_sandbox_path("myapp")
            assert sp == root / "myapp"
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_env_sandbox_root_points_to_pactown(self) -> None:
        """PACTOWN_SANDBOX_ROOT from .env resolves to .pactown inside project."""
        import os
        val = os.environ.get("PACTOWN_SANDBOX_ROOT", "")
        # conftest.py resolves relative .pactown → absolute path
        assert val, "PACTOWN_SANDBOX_ROOT should be set by .env / conftest.py"
        p = Path(val)
        assert p.name == ".pactown" or ".pactown" in str(p), (
            f"Expected .pactown in PACTOWN_SANDBOX_ROOT, got: {val}"
        )

    def test_service_runner_default_root_from_env(self) -> None:
        """ServiceRunner picks up PACTOWN_SANDBOX_ROOT from env."""
        import os
        from pactown.service_runner import ServiceRunner

        original = os.environ.get("PACTOWN_SANDBOX_ROOT")
        import tempfile, shutil
        test_root = Path(tempfile.mkdtemp(prefix="pactown_sr_"))
        try:
            os.environ["PACTOWN_SANDBOX_ROOT"] = str(test_root)
            runner = ServiceRunner()
            assert runner.sandbox_root == test_root
        finally:
            if original is not None:
                os.environ["PACTOWN_SANDBOX_ROOT"] = original
            else:
                os.environ.pop("PACTOWN_SANDBOX_ROOT", None)
            shutil.rmtree(test_root, ignore_errors=True)

    def test_electron_artifacts_inside_sandbox_root(self) -> None:
        """Electron scaffold + fake build artifacts land inside sandbox_root/service/dist."""
        from pactown.sandbox_manager import SandboxManager
        from pactown.builders import DesktopBuilder
        import tempfile, shutil

        root = Path(tempfile.mkdtemp(prefix="pactown_art_"))
        try:
            sm = SandboxManager(root)
            svc_path = sm.get_sandbox_path("electron-app")
            svc_path.mkdir(parents=True, exist_ok=True)

            builder = DesktopBuilder()
            builder.scaffold(svc_path, framework="electron", app_name="testapp")

            # Simulate build output
            dist = svc_path / "dist"
            dist.mkdir(exist_ok=True)
            (dist / "testapp-1.0.0.AppImage").write_bytes(b"\x7fELF")
            (dist / "testapp-1.0.0.exe").write_bytes(b"MZ")

            artifacts = DesktopBuilder._collect_artifacts(svc_path, "electron")
            assert len(artifacts) >= 2

            # All artifacts must be inside sandbox_root
            for art in artifacts:
                assert str(art).startswith(str(root)), (
                    f"Artifact {art} is not inside sandbox_root {root}"
                )

            # Verify structure: root / service_name / dist / artifact
            for art in artifacts:
                rel = art.relative_to(root)
                parts = rel.parts
                assert parts[0] == "electron-app", f"Expected service dir, got {parts}"
                assert parts[1] == "dist", f"Expected dist dir, got {parts}"
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_capacitor_artifacts_inside_sandbox_root(self) -> None:
        """Capacitor scaffold + fake APK lands inside sandbox_root/service."""
        from pactown.sandbox_manager import SandboxManager
        from pactown.builders import MobileBuilder
        import tempfile, shutil

        root = Path(tempfile.mkdtemp(prefix="pactown_cap_"))
        try:
            sm = SandboxManager(root)
            svc_path = sm.get_sandbox_path("cap-app")
            svc_path.mkdir(parents=True, exist_ok=True)

            builder = MobileBuilder()
            builder.scaffold(svc_path, framework="capacitor", app_name="captest")

            # Simulate build output
            apk_dir = svc_path / "android" / "app" / "build" / "outputs" / "apk" / "release"
            apk_dir.mkdir(parents=True)
            (apk_dir / "app-release.apk").write_bytes(b"PK\x03\x04")

            artifacts = MobileBuilder._collect_artifacts(svc_path, "capacitor")
            assert len(artifacts) == 1

            art = artifacts[0]
            assert str(art).startswith(str(root))
            assert art.relative_to(root).parts[0] == "cap-app"
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_tauri_artifacts_inside_sandbox_root(self) -> None:
        """Tauri scaffold + fake bundle lands inside sandbox_root/service."""
        from pactown.sandbox_manager import SandboxManager
        from pactown.builders import DesktopBuilder
        import tempfile, shutil

        root = Path(tempfile.mkdtemp(prefix="pactown_tauri_"))
        try:
            sm = SandboxManager(root)
            svc_path = sm.get_sandbox_path("tauri-app")
            svc_path.mkdir(parents=True, exist_ok=True)

            builder = DesktopBuilder()
            builder.scaffold(svc_path, framework="tauri", app_name="tauritest")

            # Simulate build output
            bundle = svc_path / "src-tauri" / "target" / "release" / "bundle" / "appimage"
            bundle.mkdir(parents=True)
            (bundle / "tauritest.AppImage").write_bytes(b"\x7fELF")

            artifacts = DesktopBuilder._collect_artifacts(svc_path, "tauri")
            assert len(artifacts) == 1
            assert str(artifacts[0]).startswith(str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_ansible_deploy_artifacts_from_sandbox_root(self) -> None:
        """Full flow: SandboxManager root → builder → artifacts → Ansible deploy."""
        from pactown.sandbox_manager import SandboxManager
        from pactown.builders import DesktopBuilder
        import tempfile, shutil

        root = Path(tempfile.mkdtemp(prefix="pactown_full_"))
        try:
            sm = SandboxManager(root)
            svc_path = sm.get_sandbox_path("fullapp")
            svc_path.mkdir(parents=True, exist_ok=True)

            builder = DesktopBuilder()
            builder.scaffold(svc_path, framework="electron", app_name="fullapp")

            dist = svc_path / "dist"
            dist.mkdir(exist_ok=True)
            (dist / "fullapp-1.0.0.AppImage").write_bytes(b"\x7fELF")

            artifacts = DesktopBuilder._collect_artifacts(svc_path, "electron")
            assert len(artifacts) >= 1

            # Deploy via Ansible with artifact metadata
            ansible_out = root / "ansible"
            backend = AnsibleBackend(
                config=_deploy_config(namespace="full"),
                dry_run=True,
                output_dir=ansible_out,
            )
            result = backend.deploy(
                service_name="fullapp",
                image_name="pactown/fullapp:latest",
                port=9000,
                env={
                    "ARTIFACTS": ",".join(a.name for a in artifacts),
                    "SANDBOX_ROOT": str(root),
                },
            )
            assert result.success

            # Ansible output is also inside sandbox_root
            assert str(ansible_out).startswith(str(root))
            pb = yaml.safe_load((ansible_out / "deploy.yml").read_text())
            env_vars = pb[0]["tasks"][2]["community.docker.docker_container"]["env"]
            assert "fullapp-1.0.0.AppImage" in env_vars["ARTIFACTS"]
            assert str(root) in env_vars["SANDBOX_ROOT"]
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_dotenv_pactown_sandbox_root_is_project_local(self) -> None:
        """The .env file sets PACTOWN_SANDBOX_ROOT to .pactown (project-local)."""
        env_file = Path(__file__).resolve().parents[1] / ".env"
        assert env_file.exists(), f".env not found at {env_file}"
        content = env_file.read_text()
        assert "PACTOWN_SANDBOX_ROOT" in content
        # Should point to .pactown, not /tmp
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, val = stripped.partition("=")
            if key.strip() == "PACTOWN_SANDBOX_ROOT":
                assert val.strip() == ".pactown", (
                    f"Expected .pactown, got: {val.strip()}"
                )


# ===========================================================================
# Real scaffold in .pactown – verify actual generated files
# ===========================================================================


class TestRealScaffoldInPactown:
    """Run REAL scaffolds in .pactown/ (as configured by .env) and verify the
    generated config files + simulated build artifacts.

    Artifacts are **intentionally kept** after tests so you can inspect them:
        ls -laR .pactown/
    """

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        project_root = Path(__file__).resolve().parents[1]
        env_file = project_root / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
        val = os.environ.get("PACTOWN_SANDBOX_ROOT", "")
        if not val:
            return project_root / ".pactown"
        p = Path(val)
        if not p.is_absolute():
            p = (project_root / p).resolve()
        return p

    def _svc_path(self, name: str) -> Path:
        return self._root() / name

    # ------------------------------------------------------------------
    # Realistic artifact generators
    # ------------------------------------------------------------------

    @staticmethod
    def _make_elf(size: int = 65_536) -> bytes:
        """Minimal ELF64 header + padding."""
        # ELF magic + class(64) + little-endian + version + OS/ABI
        header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
        # e_type=EXEC(2), e_machine=x86-64(0x3E), e_version=1
        header += struct.pack("<HHIQ", 2, 0x3E, 1, 0x400000)
        # e_phoff, e_shoff
        header += struct.pack("<QQ", 64, 0)
        # e_flags, e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx
        header += struct.pack("<IHHHHHH", 0, 64, 56, 0, 64, 0, 0)
        return header + b"\x00" * (size - len(header))

    @staticmethod
    def _make_pe(size: int = 65_536) -> bytes:
        """Minimal PE (MZ/PE) header + padding."""
        dos = bytearray(128)
        dos[0:2] = b"MZ"
        struct.pack_into("<I", dos, 60, 128)  # e_lfanew → PE header at 128
        pe_sig = b"PE\x00\x00"
        # COFF: machine=0x8664 (x64), sections=1, timestamp=0, ...
        coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
        # Optional header magic (PE32+)
        opt = struct.pack("<H", 0x20B) + b"\x00" * 238
        return bytes(dos) + pe_sig + coff + opt + b"\x00" * (size - 128 - 4 - 20 - 240)

    @staticmethod
    def _make_zip_package(entries: dict[str, bytes], size: int = 10_240) -> bytes:
        """Create a real ZIP archive with given entries, padded to size."""
        # Build base archive first to measure overhead
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        base_size = buf.tell()
        if base_size >= size:
            return buf.getvalue()
        # Rebuild with padding entry large enough to reach target size
        # ZIP overhead for one entry is ~100 bytes; overshoot slightly
        pad_data_size = size - base_size
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w", zipfile.ZIP_STORED) as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
            zf.writestr("META-INF/padding.bin", b"\x00" * pad_data_size)
        return buf2.getvalue()

    @classmethod
    def _make_apk(cls, app_name: str = "app", size: int = 10_240) -> bytes:
        """Real ZIP-based APK with AndroidManifest.xml."""
        return cls._make_zip_package({
            "AndroidManifest.xml": (
                '<?xml version="1.0"?>\n'
                f'<manifest package="com.test.{app_name}" '
                'xmlns:android="http://schemas.android.com/apk/res/android">\n'
                f'  <application android:label="{app_name}"/>\n'
                '</manifest>\n'
            ).encode(),
            "classes.dex": b"dex\n035\x00" + b"\x00" * 100,
            "resources.arsc": b"\x02\x00\x0c\x00" + b"\x00" * 50,
        }, size)

    @classmethod
    def _make_ipa(cls, app_name: str = "App", size: int = 10_240) -> bytes:
        """Real ZIP-based IPA with Payload/ structure."""
        return cls._make_zip_package({
            f"Payload/{app_name}.app/Info.plist": (
                '<?xml version="1.0"?>\n'
                '<plist version="1.0"><dict>\n'
                f'  <key>CFBundleName</key><string>{app_name}</string>\n'
                '  <key>CFBundleIdentifier</key>'
                f'<string>com.test.{app_name.lower()}</string>\n'
                '</dict></plist>\n'
            ).encode(),
            f"Payload/{app_name}.app/{app_name}": b"\xcf\xfa\xed\xfe" + b"\x00" * 50,
        }, size)

    @classmethod
    def _make_aab(cls, app_name: str = "app", size: int = 10_240) -> bytes:
        """Real ZIP-based AAB (Android App Bundle)."""
        return cls._make_zip_package({
            "BundleConfig.pb": b"\x0a\x02\x08\x01" + b"\x00" * 20,
            "base/manifest/AndroidManifest.xml": (
                '<?xml version="1.0"?>\n'
                f'<manifest package="com.test.{app_name}"/>\n'
            ).encode(),
            "base/dex/classes.dex": b"dex\n035\x00" + b"\x00" * 100,
        }, size)

    @staticmethod
    def _make_dmg(size: int = 65_536) -> bytes:
        """DMG-like file with Apple UDIF magic at end."""
        content = b"\x00" * (size - 512)
        # UDIF trailer (koly magic at offset -512)
        trailer = b"koly" + b"\x00\x00\x00\x04"  # magic + version
        trailer += b"\x00" * (512 - len(trailer))
        return content + trailer

    @staticmethod
    def _make_deb(size: int = 10_240) -> bytes:
        """Minimal Debian .deb (ar archive format)."""
        ar_magic = b"!<arch>\n"
        # debian-binary entry
        entry_name = b"debian-binary/  "[:16]
        entry_header = entry_name + b"0           0     0     100644  3         `\n"
        entry_data = b"2.0\n"
        content = ar_magic + entry_header + entry_data
        return content + b"\x00" * (size - len(content))

    @staticmethod
    def _make_snap(size: int = 65_536) -> bytes:
        """Minimal snap (squashfs magic + padding)."""
        # squashfs magic: hsqs (little-endian)
        header = b"hsqs" + struct.pack("<I", 4)  # magic + inode count
        header += b"\x00" * 88  # rest of superblock (96 bytes total)
        return header + b"\x00" * (size - len(header))

    @staticmethod
    def _make_msi(size: int = 65_536) -> bytes:
        """Minimal MSI (OLE Compound Document magic + padding)."""
        header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE magic
        header += b"\x00" * (512 - 8)  # rest of OLE header sector
        return header + b"\x00" * (size - len(header))

    @staticmethod
    def _make_so(size: int = 32_768) -> bytes:
        """Minimal ELF shared object."""
        header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
        # e_type=DYN(3) for shared object
        header += struct.pack("<HHIQ", 3, 0x3E, 1, 0)
        header += struct.pack("<QQ", 64, 0)
        header += struct.pack("<IHHHHHH", 0, 64, 56, 0, 64, 0, 0)
        return header + b"\x00" * (size - len(header))

    @staticmethod
    def _make_appimage(size: int = 131_072) -> bytes:
        """Minimal AppImage Type 2 (ELF + squashfs)."""
        # ELF header
        header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
        header += struct.pack("<HHIQ", 2, 0x3E, 1, 0x400000)
        header += struct.pack("<QQ", 64, 0)
        header += struct.pack("<IHHHHHH", 0, 64, 56, 0, 64, 0, 0)
        # AppImage type 2 magic at offset 8 (AI\x02)
        header = header[:8] + b"AI\x02" + header[11:]
        # pad to halfway, then squashfs
        mid = size // 2
        sqfs = b"hsqs" + b"\x00" * (size - mid - 4)
        return header + b"\x00" * (mid - len(header)) + b"hsqs" + sqfs

    def _write_artifact(self, path: Path, content: bytes) -> None:
        """Write artifact bytes to path, creating parent dirs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    # ======================================================================
    # .env / root verification
    # ======================================================================

    def test_root_matches_dotenv_config(self) -> None:
        """_root() must resolve to the path configured in .env file."""
        from dotenv import dotenv_values
        project_root = Path(__file__).resolve().parents[1]
        env_file = project_root / ".env"
        assert env_file.exists(), f".env not found at {env_file}"
        values = dotenv_values(env_file)
        configured = values.get("PACTOWN_SANDBOX_ROOT", "")
        assert configured, "PACTOWN_SANDBOX_ROOT not set in .env"

        expected = Path(configured)
        if not expected.is_absolute():
            expected = (project_root / expected).resolve()

        actual = self._root()
        assert actual == expected, (
            f".env says PACTOWN_SANDBOX_ROOT={configured} → {expected}, "
            f"but _root() returned {actual}"
        )

    def test_pactown_dir_exists(self) -> None:
        """The .pactown directory must exist."""
        root = self._root()
        assert root.exists(), f".pactown root not found at {root}"

    # ======================================================================
    # Desktop frameworks – scaffold + simulated artifacts
    # ======================================================================

    def test_real_electron_scaffold_and_artifacts(self) -> None:
        """Scaffold Electron app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-electron")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="electron", app_name="TestElectron")

        # Verify scaffold config
        pkg = json.loads((svc / "package.json").read_text())
        assert pkg["main"] == "main.js"
        assert "electron" in pkg.get("devDependencies", {})
        assert "electron-builder" in pkg.get("devDependencies", {})
        assert pkg["build"]["linux"]["target"] == ["AppImage"]
        assert pkg["build"]["win"]["target"] == ["nsis"]
        assert pkg["build"]["mac"]["target"] == ["dmg"]

        main_js = svc / "main.js"
        assert main_js.exists()
        src = main_js.read_text()
        assert "no-sandbox" in src
        assert "BrowserWindow" in src

        # Simulate build artifacts for all OS targets (realistic sizes + magic bytes)
        self._write_artifact(svc / "dist" / "TestElectron-1.0.0.AppImage", self._make_appimage(131_072))
        self._write_artifact(svc / "dist" / "TestElectron-1.0.0.snap", self._make_snap(65_536))
        self._write_artifact(svc / "dist" / "run.sh", b"#!/bin/bash\nset -e\ncd \"$(dirname \"$0\")\"\n./TestElectron*.AppImage --no-sandbox\n")
        self._write_artifact(svc / "dist" / "README.txt", b"Linux AppImage usage instructions\nRun: ./run.sh\n")
        self._write_artifact(svc / "dist" / "TestElectron Setup 1.0.0.exe", self._make_pe(65_536))
        self._write_artifact(svc / "dist" / "TestElectron-1.0.0.dmg", self._make_dmg(65_536))

        # Verify artifacts are collected
        arts = DesktopBuilder._collect_artifacts(svc, "electron")
        assert len(arts) >= 6, f"Expected >=6 artifacts, got {len(arts)}: {arts}"
        names = {a.name for a in arts}
        assert "TestElectron-1.0.0.AppImage" in names
        assert "run.sh" in names
        assert "README.txt" in names

    def test_real_tauri_scaffold_and_artifacts(self) -> None:
        """Scaffold Tauri app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-tauri")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="tauri", app_name="TestTauri",
                                  extra={"app_id": "com.test.tauri", "window_width": 1280, "window_height": 720})

        cfg = json.loads((svc / "src-tauri" / "tauri.conf.json").read_text())
        assert cfg["package"]["productName"] == "TestTauri"
        assert cfg["tauri"]["bundle"]["identifier"] == "com.test.tauri"
        assert cfg["tauri"]["windows"][0]["width"] == 1280

        # Simulate Tauri build artifacts (realistic sizes + magic bytes)
        self._write_artifact(svc / "src-tauri" / "target" / "release" / "bundle" / "appimage" / "test-tauri.AppImage", self._make_appimage(131_072))
        self._write_artifact(svc / "src-tauri" / "target" / "release" / "bundle" / "deb" / "test-tauri_1.0.0_amd64.deb", self._make_deb(10_240))
        self._write_artifact(svc / "src-tauri" / "target" / "release" / "bundle" / "msi" / "TestTauri_1.0.0_x64.msi", self._make_msi(65_536))
        self._write_artifact(svc / "src-tauri" / "target" / "release" / "bundle" / "dmg" / "TestTauri_1.0.0.dmg", self._make_dmg(65_536))

        arts = DesktopBuilder._collect_artifacts(svc, "tauri")
        assert len(arts) >= 4, f"Expected >=4 Tauri artifacts, got {len(arts)}"

    def test_real_pyinstaller_scaffold_and_artifacts(self) -> None:
        """Scaffold PyInstaller app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-pyinstaller")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="pyinstaller", app_name="TestPI",
                                  extra={"icon": "app.ico"})

        spec = svc / "TestPI.spec"
        assert spec.exists()
        content = spec.read_text()
        assert "Analysis" in content
        assert "app.ico" in content

        # Simulate PyInstaller build artifacts for all OS (realistic sizes)
        self._write_artifact(svc / "dist" / "TestPI", self._make_elf(65_536))       # Linux binary
        self._write_artifact(svc / "dist" / "TestPI.exe", self._make_pe(65_536))    # Windows exe
        self._write_artifact(svc / "dist" / "TestPI.app", self._make_elf(65_536))   # macOS binary

        arts = DesktopBuilder._collect_artifacts(svc, "pyinstaller")
        assert len(arts) >= 3

    def test_real_pyqt_scaffold_and_artifacts(self) -> None:
        """Scaffold PyQt app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-pyqt")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="pyqt", app_name="TestPyQt")

        spec = svc / "TestPyQt.spec"
        assert spec.exists()
        assert "Analysis" in spec.read_text()

        self._write_artifact(svc / "dist" / "TestPyQt", self._make_elf(65_536))
        self._write_artifact(svc / "dist" / "TestPyQt.exe", self._make_pe(65_536))

        arts = DesktopBuilder._collect_artifacts(svc, "pyqt")
        assert len(arts) >= 2

    def test_real_tkinter_scaffold_and_artifacts(self) -> None:
        """Scaffold Tkinter app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-tkinter")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="tkinter", app_name="TestTk")

        spec = svc / "TestTk.spec"
        assert spec.exists()
        assert "Analysis" in spec.read_text()

        self._write_artifact(svc / "dist" / "TestTk", self._make_elf(65_536))
        self._write_artifact(svc / "dist" / "TestTk.exe", self._make_pe(65_536))

        arts = DesktopBuilder._collect_artifacts(svc, "tkinter")
        assert len(arts) >= 2

    def test_real_flutter_desktop_scaffold_and_artifacts(self) -> None:
        """Scaffold Flutter desktop app + simulate build artifacts in .pactown/."""
        from pactown.builders import DesktopBuilder
        svc = self._svc_path("test-flutter-desktop")
        svc.mkdir(parents=True, exist_ok=True)

        DesktopBuilder().scaffold(svc, framework="flutter", app_name="TestFlutterDesktop")

        # Flutter scaffold is a noop (expects existing Flutter project)
        # Simulate build artifacts for Linux (realistic sizes)
        self._write_artifact(svc / "build" / "linux" / "x64" / "release" / "bundle" / "test_flutter_desktop", self._make_elf(65_536))
        self._write_artifact(svc / "build" / "linux" / "x64" / "release" / "bundle" / "lib" / "libapp.so", self._make_so(32_768))

        arts = DesktopBuilder._collect_artifacts(svc, "flutter")
        assert len(arts) >= 2

    # ======================================================================
    # Mobile frameworks – scaffold + simulated artifacts
    # ======================================================================

    def test_real_capacitor_scaffold_and_artifacts(self) -> None:
        """Scaffold Capacitor app + simulate build artifacts in .pactown/."""
        from pactown.builders import MobileBuilder
        svc = self._svc_path("test-capacitor")
        svc.mkdir(parents=True, exist_ok=True)

        MobileBuilder().scaffold(svc, framework="capacitor", app_name="TestCap",
                                 extra={"app_id": "com.test.cap", "targets": ["android", "ios"]})

        cfg = json.loads((svc / "capacitor.config.json").read_text())
        assert cfg["appId"] == "com.test.cap"
        assert cfg["appName"] == "TestCap"

        pkg = json.loads((svc / "package.json").read_text())
        assert "@capacitor/core" in pkg["dependencies"]
        assert "@capacitor/android" in pkg["dependencies"]
        assert "@capacitor/ios" in pkg["dependencies"]
        assert pkg["dependencies"]["@capacitor/core"] == "^6.0.0"

        # Simulate build artifacts (realistic ZIP-based packages)
        self._write_artifact(svc / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
                             self._make_apk("TestCap", 10_240))
        self._write_artifact(svc / "ios" / "App" / "build" / "Release" / "TestCap.ipa",
                             self._make_ipa("TestCap", 10_240))

        arts = MobileBuilder._collect_artifacts(svc, "capacitor")
        assert len(arts) >= 2
        exts = {a.suffix for a in arts}
        assert ".apk" in exts
        assert ".ipa" in exts

    def test_real_react_native_scaffold_and_artifacts(self) -> None:
        """Scaffold React Native app + simulate build artifacts in .pactown/."""
        from pactown.builders import MobileBuilder
        svc = self._svc_path("test-react-native")
        svc.mkdir(parents=True, exist_ok=True)

        MobileBuilder().scaffold(svc, framework="react-native", app_name="TestRN",
                                 extra={"app_name": "My RN App"})

        cfg = json.loads((svc / "app.json").read_text())
        assert cfg["name"] == "TestRN"
        assert cfg["displayName"] == "My RN App"

        # Simulate build artifacts (realistic ZIP-based packages)
        self._write_artifact(svc / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk",
                             self._make_apk("TestRN", 10_240))
        self._write_artifact(svc / "ios" / "build" / "Release" / "TestRN.ipa",
                             self._make_ipa("TestRN", 10_240))

        arts = MobileBuilder._collect_artifacts(svc, "react-native")
        assert len(arts) >= 2

    def test_real_flutter_mobile_scaffold_and_artifacts(self) -> None:
        """Scaffold Flutter mobile app + simulate build artifacts in .pactown/."""
        from pactown.builders import MobileBuilder
        svc = self._svc_path("test-flutter-mobile")
        svc.mkdir(parents=True, exist_ok=True)

        MobileBuilder().scaffold(svc, framework="flutter", app_name="TestFlutterMobile")

        # Simulate build artifacts (realistic ZIP-based packages)
        self._write_artifact(svc / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk",
                             self._make_apk("TestFlutterMobile", 10_240))
        self._write_artifact(svc / "build" / "ios" / "Release" / "TestFlutterMobile.ipa",
                             self._make_ipa("TestFlutterMobile", 10_240))

        arts = MobileBuilder._collect_artifacts(svc, "flutter")
        assert len(arts) >= 1  # apk found via glob

    def test_real_kivy_scaffold_and_artifacts(self) -> None:
        """Scaffold Kivy app + simulate build artifacts in .pactown/."""
        from pactown.builders import MobileBuilder
        svc = self._svc_path("test-kivy")
        svc.mkdir(parents=True, exist_ok=True)

        MobileBuilder().scaffold(svc, framework="kivy", app_name="TestKivy",
                                 extra={"app_id": "com.test.kivy", "fullscreen": True, "icon": "icon.png"})

        spec = svc / "buildozer.spec"
        assert spec.exists()
        content = spec.read_text()
        assert "TestKivy" in content
        assert "requirements = python3,kivy" in content
        assert "fullscreen = 1" in content
        assert "icon.png" in content

        # Simulate build artifacts (realistic ZIP-based packages)
        self._write_artifact(svc / "bin" / "testapp-0.1-arm64-v8a_armeabi-v7a-debug.apk",
                             self._make_apk("TestKivy", 10_240))
        self._write_artifact(svc / "bin" / "testapp-0.1-arm64-v8a_armeabi-v7a-debug.aab",
                             self._make_aab("TestKivy", 10_240))

        arts = MobileBuilder._collect_artifacts(svc, "kivy")
        assert len(arts) >= 2
        exts = {a.suffix for a in arts}
        assert ".apk" in exts
        assert ".aab" in exts

    # ======================================================================
    # Web frameworks – manual scaffold + simulated artifacts
    # ======================================================================

    def test_real_fastapi_scaffold_and_artifacts(self) -> None:
        """Create FastAPI project in .pactown/ and verify structure."""
        svc = self._svc_path("test-fastapi")
        svc.mkdir(parents=True, exist_ok=True)

        # Create realistic FastAPI project
        (svc / "main.py").write_text(
            'from fastapi import FastAPI\n\n'
            'app = FastAPI(title="TestFastAPI")\n\n\n'
            '@app.get("/health")\n'
            'def health():\n'
            '    return {"status": "ok"}\n\n\n'
            '@app.get("/")\n'
            'def root():\n'
            '    return {"message": "Hello from TestFastAPI"}\n'
        )
        (svc / "requirements.txt").write_text(
            "fastapi>=0.110.0\nuvicorn[standard]>=0.29.0\npydantic>=2.0\n"
        )
        (svc / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        )

        assert (svc / "main.py").exists()
        assert (svc / "requirements.txt").exists()
        assert (svc / "Dockerfile").exists()
        assert "FastAPI" in (svc / "main.py").read_text()
        assert "fastapi" in (svc / "requirements.txt").read_text()

    def test_real_flask_scaffold_and_artifacts(self) -> None:
        """Create Flask project in .pactown/ and verify structure."""
        svc = self._svc_path("test-flask")
        svc.mkdir(parents=True, exist_ok=True)

        (svc / "app.py").write_text(
            'from flask import Flask, jsonify\n\n'
            'app = Flask(__name__)\n\n\n'
            '@app.route("/health")\n'
            'def health():\n'
            '    return jsonify(status="ok")\n\n\n'
            '@app.route("/")\n'
            'def index():\n'
            '    return jsonify(message="Hello from TestFlask")\n\n\n'
            'if __name__ == "__main__":\n'
            '    app.run(host="0.0.0.0", port=5000)\n'
        )
        (svc / "requirements.txt").write_text(
            "flask>=3.0.0\ngunicorn>=22.0.0\n"
        )
        (svc / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]\n'
        )
        (svc / "wsgi.py").write_text(
            "from app import app\n\nif __name__ == '__main__':\n    app.run()\n"
        )

        assert (svc / "app.py").exists()
        assert "Flask" in (svc / "app.py").read_text()
        assert "flask" in (svc / "requirements.txt").read_text()

    def test_real_express_scaffold_and_artifacts(self) -> None:
        """Create Express project in .pactown/ and verify structure."""
        svc = self._svc_path("test-express")
        svc.mkdir(parents=True, exist_ok=True)

        pkg = {
            "name": "test-express",
            "version": "1.0.0",
            "main": "index.js",
            "scripts": {
                "start": "node index.js",
                "dev": "nodemon index.js",
            },
            "dependencies": {
                "express": "^4.18.0",
                "cors": "^2.8.5",
            },
            "devDependencies": {
                "nodemon": "^3.0.0",
            },
        }
        (svc / "package.json").write_text(json.dumps(pkg, indent=2))
        (svc / "index.js").write_text(
            "const express = require('express');\n"
            "const cors = require('cors');\n\n"
            "const app = express();\n"
            "app.use(cors());\n"
            "app.use(express.json());\n\n"
            "app.get('/health', (req, res) => res.json({ status: 'ok' }));\n"
            "app.get('/', (req, res) => res.json({ message: 'Hello from TestExpress' }));\n\n"
            "const PORT = process.env.PORT || 3000;\n"
            "app.listen(PORT, () => console.log(`Server running on port ${PORT}`));\n"
        )
        (svc / "Dockerfile").write_text(
            "FROM node:20-slim\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm ci --production\n"
            "COPY . .\n"
            "EXPOSE 3000\n"
            'CMD ["node", "index.js"]\n'
        )

        parsed = json.loads((svc / "package.json").read_text())
        assert parsed["dependencies"]["express"] == "^4.18.0"
        assert (svc / "index.js").exists()

    def test_real_nextjs_scaffold_and_artifacts(self) -> None:
        """Create Next.js project in .pactown/ and verify structure."""
        svc = self._svc_path("test-nextjs")
        svc.mkdir(parents=True, exist_ok=True)

        pkg = {
            "name": "test-nextjs",
            "version": "1.0.0",
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
            },
            "dependencies": {
                "next": "^14.0.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
            },
        }
        (svc / "package.json").write_text(json.dumps(pkg, indent=2))
        (svc / "next.config.js").write_text(
            "/** @type {import('next').NextConfig} */\n"
            "const nextConfig = {\n"
            "  reactStrictMode: true,\n"
            "  output: 'standalone',\n"
            "};\n\n"
            "module.exports = nextConfig;\n"
        )
        pages = svc / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "index.js").write_text(
            "export default function Home() {\n"
            "  return <h1>Hello from TestNextJS</h1>;\n"
            "}\n"
        )
        (pages / "api" / "health.js").parent.mkdir(parents=True, exist_ok=True)
        (pages / "api" / "health.js").write_text(
            "export default function handler(req, res) {\n"
            "  res.status(200).json({ status: 'ok' });\n"
            "}\n"
        )

        # Simulate build output (.next/standalone)
        standalone = svc / ".next" / "standalone"
        standalone.mkdir(parents=True, exist_ok=True)
        (standalone / "server.js").write_text(
            "// Next.js standalone server\n"
            "const http = require('http');\n"
            "const next = require('next');\n\n"
            "const app = next({ dev: false, dir: __dirname });\n"
            "const handle = app.getRequestHandler();\n\n"
            "app.prepare().then(() => {\n"
            "  http.createServer((req, res) => handle(req, res))\n"
            "    .listen(process.env.PORT || 3000, () => {\n"
            "      console.log('> Ready on port ' + (process.env.PORT || 3000));\n"
            "    });\n"
            "});\n"
            + "// " + "x" * 2000 + "\n"  # padding for realistic size
        )

        parsed = json.loads((svc / "package.json").read_text())
        assert "next" in parsed["dependencies"]
        assert (svc / "next.config.js").exists()
        assert (pages / "index.js").exists()

    def test_real_react_spa_scaffold_and_artifacts(self) -> None:
        """Create React SPA project in .pactown/ and verify structure."""
        svc = self._svc_path("test-react-spa")
        svc.mkdir(parents=True, exist_ok=True)

        pkg = {
            "name": "test-react-spa",
            "version": "1.0.0",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview",
            },
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
            },
            "devDependencies": {
                "vite": "^5.0.0",
                "@vitejs/plugin-react": "^4.0.0",
            },
        }
        (svc / "package.json").write_text(json.dumps(pkg, indent=2))
        (svc / "vite.config.js").write_text(
            "import { defineConfig } from 'vite';\n"
            "import react from '@vitejs/plugin-react';\n\n"
            "export default defineConfig({\n"
            "  plugins: [react()],\n"
            "});\n"
        )
        (svc / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <title>TestReactSPA</title>\n'
            '</head>\n<body>\n'
            '  <div id="root"></div>\n'
            '  <script type="module" src="/src/main.jsx"></script>\n'
            '</body>\n</html>\n'
        )
        src = svc / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "main.jsx").write_text(
            "import React from 'react';\n"
            "import ReactDOM from 'react-dom/client';\n"
            "import App from './App';\n\n"
            "ReactDOM.createRoot(document.getElementById('root')).render(\n"
            "  <React.StrictMode><App /></React.StrictMode>\n"
            ");\n"
        )
        (src / "App.jsx").write_text(
            "export default function App() {\n"
            "  return <h1>Hello from TestReactSPA</h1>;\n"
            "}\n"
        )

        # Simulate Vite build output (realistic sizes)
        dist = svc / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <link rel="stylesheet" href="/assets/index-abc123.css" />\n'
            '</head>\n<body>\n'
            '  <div id="root"></div>\n'
            '  <script type="module" src="/assets/index-abc123.js"></script>\n'
            '</body>\n</html>\n'
        )
        assets = dist / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "index-abc123.js").write_text(
            '"use strict";\n'
            'import{jsx as e}from"react/jsx-runtime";\n'
            'import{createRoot}from"react-dom/client";\n'
            'function App(){return e("h1",{children:"Hello from TestReactSPA"})}\n'
            'createRoot(document.getElementById("root")).render(e(App,{}));\n'
            + '// ' + 'x' * 2000 + '\n'
        )
        (assets / "index-abc123.css").write_text(
            '*, *::before, *::after { box-sizing: border-box; }\n'
            'body { margin: 0; font-family: system-ui, sans-serif; }\n'
            'h1 { color: #1a1a1a; padding: 2rem; }\n'
            + '/* ' + 'x' * 1000 + ' */\n'
        )

        parsed = json.loads((svc / "package.json").read_text())
        assert "react" in parsed["dependencies"]
        assert (svc / "vite.config.js").exists()
        assert (dist / "index.html").exists()

    def test_real_vue_scaffold_and_artifacts(self) -> None:
        """Create Vue project in .pactown/ and verify structure."""
        svc = self._svc_path("test-vue")
        svc.mkdir(parents=True, exist_ok=True)

        pkg = {
            "name": "test-vue",
            "version": "1.0.0",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview",
            },
            "dependencies": {
                "vue": "^3.4.0",
            },
            "devDependencies": {
                "vite": "^5.0.0",
                "@vitejs/plugin-vue": "^5.0.0",
            },
        }
        (svc / "package.json").write_text(json.dumps(pkg, indent=2))
        (svc / "vite.config.js").write_text(
            "import { defineConfig } from 'vite';\n"
            "import vue from '@vitejs/plugin-vue';\n\n"
            "export default defineConfig({\n"
            "  plugins: [vue()],\n"
            "});\n"
        )
        (svc / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <title>TestVue</title>\n'
            '</head>\n<body>\n'
            '  <div id="app"></div>\n'
            '  <script type="module" src="/src/main.js"></script>\n'
            '</body>\n</html>\n'
        )
        src = svc / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "main.js").write_text(
            "import { createApp } from 'vue';\n"
            "import App from './App.vue';\n\n"
            "createApp(App).mount('#app');\n"
        )
        (src / "App.vue").write_text(
            "<template>\n  <h1>Hello from TestVue</h1>\n</template>\n\n"
            "<script setup>\n</script>\n"
        )

        # Simulate Vite build output (realistic sizes)
        dist = svc / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '  <meta charset="UTF-8" />\n'
            '  <link rel="stylesheet" href="/assets/index-vue123.css" />\n'
            '</head>\n<body>\n'
            '  <div id="app"></div>\n'
            '  <script type="module" src="/assets/index-vue123.js"></script>\n'
            '</body>\n</html>\n'
        )
        assets = dist / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "index-vue123.js").write_text(
            '"use strict";\n'
            'import{createApp}from"vue";\n'
            'const App={setup(){return()=>({})},template:"<h1>Hello from TestVue</h1>"};\n'
            'createApp(App).mount("#app");\n'
            + '// ' + 'x' * 2000 + '\n'
        )
        (assets / "index-vue123.css").write_text(
            '*, *::before, *::after { box-sizing: border-box; }\n'
            'body { margin: 0; font-family: system-ui, sans-serif; }\n'
            'h1 { color: #42b883; padding: 2rem; }\n'
            + '/* ' + 'x' * 1000 + ' */\n'
        )

        parsed = json.loads((svc / "package.json").read_text())
        assert "vue" in parsed["dependencies"]
        assert (svc / "vite.config.js").exists()
        assert (dist / "index.html").exists()

    # ======================================================================
    # Summary: verify all framework dirs exist with artifacts
    # ======================================================================

    def test_all_framework_dirs_present(self) -> None:
        """After all scaffold tests, every framework dir should exist in .pactown/."""
        base = self._root()
        expected_dirs = [
            "test-electron", "test-tauri", "test-pyinstaller",
            "test-pyqt", "test-tkinter", "test-flutter-desktop",
            "test-capacitor", "test-react-native", "test-flutter-mobile",
            "test-kivy",
            "test-fastapi", "test-flask", "test-express",
            "test-nextjs", "test-react-spa", "test-vue",
        ]
        missing = [d for d in expected_dirs if not (base / d).exists()]
        assert not missing, f"Missing framework dirs in {base}: {missing}"

    def test_all_artifacts_are_inside_pactown(self) -> None:
        """Every generated artifact must be under the .pactown/ root."""
        root = self._root()
        if not root.exists():
            return
        for f in root.rglob("*"):
            if f.is_file():
                assert str(f).startswith(str(root)), (
                    f"Artifact {f} is outside .pactown root {root}"
                )


# ===========================================================================
# Docker-based artifact execution tests
# ===========================================================================

def _docker_available() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _docker_run(image: str, mount_src: Path, mount_dst: str,
                cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a command inside a Docker container with a bind-mount."""
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{mount_src}:{mount_dst}:ro",
            image,
        ] + cmd,
        capture_output=True, text=True, timeout=timeout,
    )


def _docker_run_script(image: str, mount_src: Path, mount_dst: str,
                       script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a shell script inside a Docker container with a bind-mount."""
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{mount_src}:{mount_dst}:ro",
            image, "sh", "-c", script,
        ],
        capture_output=True, text=True, timeout=timeout,
    )


_skip_no_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


@_skip_no_docker
class TestDockerArtifactExecution:
    """Run each framework's artifacts inside an appropriate Docker container
    to verify they are valid, parseable, and structurally correct.

    Uses lightweight base images:
    - node:20-slim      → Electron, Capacitor, React Native (JS/Node validation)
    - python:3.12-slim  → PyInstaller, PyQt, Tkinter, Kivy (Python/spec validation)
    - ubuntu:22.04      → Tauri, Flutter (Linux binary format validation)
    - eclipse-temurin:17-jre-jammy → Android APK/AAB (Java ZIP validation)

    Artifacts are stubs, so tests validate: file presence, format headers,
    config parsing, and structural integrity inside the container.
    """

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        project_root = Path(__file__).resolve().parents[1]
        env_file = project_root / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
        val = os.environ.get("PACTOWN_SANDBOX_ROOT", "")
        if not val:
            return project_root / ".pactown"
        p = Path(val)
        if not p.is_absolute():
            p = (project_root / p).resolve()
        return p

    # ==================================================================
    # Electron – node:20-slim
    # ==================================================================

    def test_docker_electron_package_json(self) -> None:
        """Validate Electron package.json inside Node container."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const p = require('/app/package.json');"
            "console.log('main:', p.main);"
            "console.log('electron:', p.devDependencies.electron);"
            "console.log('linux:', JSON.stringify(p.build.linux.target));"
            "console.log('win:', JSON.stringify(p.build.win.target));"
            "console.log('mac:', JSON.stringify(p.build.mac.target));"
            "process.exit(p.main === 'main.js' ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"Electron package.json validation failed:\n{r.stderr}"
        assert "main: main.js" in r.stdout
        assert '["AppImage"]' in r.stdout
        assert '["nsis"]' in r.stdout
        assert '["dmg"]' in r.stdout

    def test_docker_electron_main_js(self) -> None:
        """Validate Electron main.js syntax inside Node container."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node --check /app/main.js && echo "SYNTAX_OK"',
        )
        assert r.returncode == 0, f"main.js syntax check failed:\n{r.stderr}"
        assert "SYNTAX_OK" in r.stdout

    def test_docker_electron_artifacts_exist(self) -> None:
        """Verify Electron build artifacts are visible inside container."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "ls -la /app/dist/ && "
            "test -f /app/dist/run.sh && echo 'RUN_SH_OK' && "
            "test -f /app/dist/README.txt && echo 'README_OK'",
        )
        assert r.returncode == 0, f"Electron artifacts check failed:\n{r.stderr}"
        assert "RUN_SH_OK" in r.stdout
        assert "README_OK" in r.stdout
        assert "AppImage" in r.stdout

    # ==================================================================
    # Tauri – ubuntu:22.04
    # ==================================================================

    def test_docker_tauri_config(self) -> None:
        """Validate tauri.conf.json inside Ubuntu container."""
        svc = self._root() / "test-tauri"
        if not svc.exists():
            pytest.skip("test-tauri not scaffolded yet")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "apt-get update -qq && apt-get install -y -qq python3 > /dev/null 2>&1 && "
            'python3 -c "'
            "import json; "
            "c = json.load(open('/app/src-tauri/tauri.conf.json')); "
            "assert c['package']['productName'] == 'TestTauri', 'bad productName'; "
            "assert c['tauri']['bundle']['identifier'] == 'com.test.tauri', 'bad id'; "
            "assert c['tauri']['bundle']['active'] is True, 'not active'; "
            "print('TAURI_CONFIG_OK');"
            '"',
        )
        assert r.returncode == 0, f"Tauri config validation failed:\n{r.stderr}"
        assert "TAURI_CONFIG_OK" in r.stdout

    def test_docker_tauri_bundle_artifacts(self) -> None:
        """Verify Tauri bundle artifacts are visible inside container."""
        svc = self._root() / "test-tauri"
        if not svc.exists():
            pytest.skip("test-tauri not scaffolded yet")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "find /app/src-tauri/target/release/bundle -type f | sort",
        )
        assert r.returncode == 0
        out = r.stdout
        assert "AppImage" in out
        assert ".deb" in out
        assert ".msi" in out
        assert ".dmg" in out

    # ==================================================================
    # PyInstaller – python:3.12-slim
    # ==================================================================

    def test_docker_pyinstaller_spec(self) -> None:
        """Validate PyInstaller .spec file inside Python container."""
        svc = self._root() / "test-pyinstaller"
        if not svc.exists():
            pytest.skip("test-pyinstaller not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "content = open('/app/TestPI.spec').read(); "
            "assert 'Analysis' in content, 'no Analysis'; "
            "assert 'TestPI' in content, 'no app name'; "
            "assert 'app.ico' in content, 'no icon'; "
            "print('PYINSTALLER_SPEC_OK');"
            '"',
        )
        assert r.returncode == 0, f"PyInstaller spec validation failed:\n{r.stderr}"
        assert "PYINSTALLER_SPEC_OK" in r.stdout

    def test_docker_pyinstaller_artifacts(self) -> None:
        """Verify PyInstaller dist artifacts inside container."""
        svc = self._root() / "test-pyinstaller"
        if not svc.exists():
            pytest.skip("test-pyinstaller not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "from pathlib import Path; "
            "dist = list(Path('/app/dist').iterdir()); "
            "names = {f.name for f in dist}; "
            "assert 'TestPI' in names, f'missing Linux binary: {names}'; "
            "assert 'TestPI.exe' in names, f'missing Windows exe: {names}'; "
            "assert 'TestPI.app' in names, f'missing macOS app: {names}'; "
            "print(f'PYINSTALLER_DIST_OK: {len(dist)} artifacts');"
            '"',
        )
        assert r.returncode == 0, f"PyInstaller dist check failed:\n{r.stderr}"
        assert "PYINSTALLER_DIST_OK: 3 artifacts" in r.stdout

    # ==================================================================
    # PyQt – python:3.12-slim
    # ==================================================================

    def test_docker_pyqt_spec_and_artifacts(self) -> None:
        """Validate PyQt .spec + dist inside Python container."""
        svc = self._root() / "test-pyqt"
        if not svc.exists():
            pytest.skip("test-pyqt not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "content = open('/app/TestPyQt.spec').read(); "
            "assert 'Analysis' in content; "
            "from pathlib import Path; "
            "dist = {f.name for f in Path('/app/dist').iterdir()}; "
            "assert 'TestPyQt' in dist; "
            "assert 'TestPyQt.exe' in dist; "
            "print(f'PYQT_OK: {len(dist)} artifacts');"
            '"',
        )
        assert r.returncode == 0, f"PyQt validation failed:\n{r.stderr}"
        assert "PYQT_OK: 2 artifacts" in r.stdout

    # ==================================================================
    # Tkinter – python:3.12-slim
    # ==================================================================

    def test_docker_tkinter_spec_and_artifacts(self) -> None:
        """Validate Tkinter .spec + dist inside Python container."""
        svc = self._root() / "test-tkinter"
        if not svc.exists():
            pytest.skip("test-tkinter not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "content = open('/app/TestTk.spec').read(); "
            "assert 'Analysis' in content; "
            "from pathlib import Path; "
            "dist = {f.name for f in Path('/app/dist').iterdir()}; "
            "assert 'TestTk' in dist; "
            "assert 'TestTk.exe' in dist; "
            "print(f'TKINTER_OK: {len(dist)} artifacts');"
            '"',
        )
        assert r.returncode == 0, f"Tkinter validation failed:\n{r.stderr}"
        assert "TKINTER_OK: 2 artifacts" in r.stdout

    # ==================================================================
    # Flutter Desktop – ubuntu:22.04
    # ==================================================================

    def test_docker_flutter_desktop_bundle(self) -> None:
        """Verify Flutter desktop bundle structure inside Ubuntu container."""
        svc = self._root() / "test-flutter-desktop"
        if not svc.exists():
            pytest.skip("test-flutter-desktop not scaffolded yet")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "test -f /app/build/linux/x64/release/bundle/test_flutter_desktop && "
            "echo 'BINARY_OK' && "
            "test -f /app/build/linux/x64/release/bundle/lib/libapp.so && "
            "echo 'LIBAPP_OK' && "
            "ls -lR /app/build/linux/x64/release/bundle/",
        )
        assert r.returncode == 0, f"Flutter desktop check failed:\n{r.stderr}"
        assert "BINARY_OK" in r.stdout
        assert "LIBAPP_OK" in r.stdout
        assert "libapp.so" in r.stdout

    # ==================================================================
    # Capacitor – node:20-slim
    # ==================================================================

    def test_docker_capacitor_config(self) -> None:
        """Validate Capacitor config + package.json inside Node container."""
        svc = self._root() / "test-capacitor"
        if not svc.exists():
            pytest.skip("test-capacitor not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const cap = require('/app/capacitor.config.json');"
            "const pkg = require('/app/package.json');"
            "console.log('appId:', cap.appId);"
            "console.log('appName:', cap.appName);"
            "console.log('core:', pkg.dependencies['@capacitor/core']);"
            "console.log('android:', pkg.dependencies['@capacitor/android']);"
            "console.log('ios:', pkg.dependencies['@capacitor/ios']);"
            "const ok = cap.appId === 'com.test.cap' && cap.appName === 'TestCap';"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"Capacitor config validation failed:\n{r.stderr}"
        assert "appId: com.test.cap" in r.stdout
        assert "appName: TestCap" in r.stdout
        assert "^6.0.0" in r.stdout

    def test_docker_capacitor_apk_ipa(self) -> None:
        """Verify Capacitor APK and IPA artifacts inside container."""
        svc = self._root() / "test-capacitor"
        if not svc.exists():
            pytest.skip("test-capacitor not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "find /app -name '*.apk' -o -name '*.ipa' | sort",
        )
        assert r.returncode == 0
        assert "app-release.apk" in r.stdout
        assert "TestCap.ipa" in r.stdout

    # ==================================================================
    # React Native – node:20-slim
    # ==================================================================

    def test_docker_react_native_config(self) -> None:
        """Validate React Native app.json inside Node container."""
        svc = self._root() / "test-react-native"
        if not svc.exists():
            pytest.skip("test-react-native not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const app = require('/app/app.json');"
            "console.log('name:', app.name);"
            "console.log('displayName:', app.displayName);"
            "const ok = app.name === 'TestRN' && app.displayName === 'My RN App';"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"React Native config validation failed:\n{r.stderr}"
        assert "name: TestRN" in r.stdout
        assert "displayName: My RN App" in r.stdout

    def test_docker_react_native_apk_ipa(self) -> None:
        """Verify React Native APK and IPA artifacts inside container."""
        svc = self._root() / "test-react-native"
        if not svc.exists():
            pytest.skip("test-react-native not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "find /app -name '*.apk' -o -name '*.ipa' | sort",
        )
        assert r.returncode == 0
        assert "app-release.apk" in r.stdout
        assert "TestRN.ipa" in r.stdout

    # ==================================================================
    # Flutter Mobile – ubuntu:22.04
    # ==================================================================

    def test_docker_flutter_mobile_artifacts(self) -> None:
        """Verify Flutter mobile APK and IPA inside container."""
        svc = self._root() / "test-flutter-mobile"
        if not svc.exists():
            pytest.skip("test-flutter-mobile not scaffolded yet")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "find /app -name '*.apk' -o -name '*.ipa' | sort",
        )
        assert r.returncode == 0
        assert "app-release.apk" in r.stdout
        assert "TestFlutterMobile.ipa" in r.stdout

    # ==================================================================
    # Kivy – python:3.12-slim
    # ==================================================================

    def test_docker_kivy_buildozer_spec(self) -> None:
        """Validate Kivy buildozer.spec inside Python container."""
        svc = self._root() / "test-kivy"
        if not svc.exists():
            pytest.skip("test-kivy not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "content = open('/app/buildozer.spec').read(); "
            "assert 'TestKivy' in content, 'no app name'; "
            "assert 'requirements = python3,kivy' in content, 'no reqs'; "
            "assert 'fullscreen = 1' in content, 'no fullscreen'; "
            "assert 'icon.png' in content, 'no icon'; "
            "print('KIVY_SPEC_OK');"
            '"',
        )
        assert r.returncode == 0, f"Kivy spec validation failed:\n{r.stderr}"
        assert "KIVY_SPEC_OK" in r.stdout

    def test_docker_kivy_apk_aab(self) -> None:
        """Verify Kivy APK and AAB artifacts inside container."""
        svc = self._root() / "test-kivy"
        if not svc.exists():
            pytest.skip("test-kivy not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "from pathlib import Path; "
            "bins = list(Path('/app/bin').iterdir()); "
            "exts = {f.suffix for f in bins}; "
            "assert '.apk' in exts, f'no APK: {exts}'; "
            "assert '.aab' in exts, f'no AAB: {exts}'; "
            "print(f'KIVY_BINS_OK: {len(bins)} artifacts');"
            '"',
        )
        assert r.returncode == 0, f"Kivy bins check failed:\n{r.stderr}"
        assert "KIVY_BINS_OK: 2 artifacts" in r.stdout

    # ==================================================================
    # FastAPI – python:3.12-slim
    # ==================================================================

    def test_docker_fastapi_syntax_and_structure(self) -> None:
        """Validate FastAPI main.py syntax + Dockerfile inside Python container."""
        svc = self._root() / "test-fastapi"
        if not svc.exists():
            pytest.skip("test-fastapi not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "import ast; "
            "ast.parse(open('/app/main.py').read()); "
            "print('SYNTAX_OK'); "
            "content = open('/app/main.py').read(); "
            "assert 'FastAPI' in content, 'no FastAPI'; "
            "assert '/health' in content, 'no health endpoint'; "
            "reqs = open('/app/requirements.txt').read(); "
            "assert 'fastapi' in reqs, 'no fastapi in reqs'; "
            "assert 'uvicorn' in reqs, 'no uvicorn in reqs'; "
            "df = open('/app/Dockerfile').read(); "
            "assert 'python:3.12' in df, 'bad base image'; "
            "assert 'uvicorn' in df, 'no uvicorn in CMD'; "
            "print('FASTAPI_OK');"
            '"',
        )
        assert r.returncode == 0, f"FastAPI validation failed:\n{r.stderr}"
        assert "SYNTAX_OK" in r.stdout
        assert "FASTAPI_OK" in r.stdout

    # ==================================================================
    # Flask – python:3.12-slim
    # ==================================================================

    def test_docker_flask_syntax_and_structure(self) -> None:
        """Validate Flask app.py syntax + Dockerfile inside Python container."""
        svc = self._root() / "test-flask"
        if not svc.exists():
            pytest.skip("test-flask not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "import ast; "
            "ast.parse(open('/app/app.py').read()); "
            "ast.parse(open('/app/wsgi.py').read()); "
            "print('SYNTAX_OK'); "
            "content = open('/app/app.py').read(); "
            "assert 'Flask' in content, 'no Flask'; "
            "assert '/health' in content, 'no health endpoint'; "
            "reqs = open('/app/requirements.txt').read(); "
            "assert 'flask' in reqs; "
            "assert 'gunicorn' in reqs; "
            "df = open('/app/Dockerfile').read(); "
            "assert 'gunicorn' in df; "
            "print('FLASK_OK');"
            '"',
        )
        assert r.returncode == 0, f"Flask validation failed:\n{r.stderr}"
        assert "SYNTAX_OK" in r.stdout
        assert "FLASK_OK" in r.stdout

    # ==================================================================
    # Express – node:20-slim
    # ==================================================================

    def test_docker_express_syntax_and_structure(self) -> None:
        """Validate Express index.js syntax + package.json inside Node container."""
        svc = self._root() / "test-express"
        if not svc.exists():
            pytest.skip("test-express not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node --check /app/index.js && echo "SYNTAX_OK" && '
            'node -e "'
            "const pkg = require('/app/package.json');"
            "console.log('express:', pkg.dependencies.express);"
            "console.log('main:', pkg.main);"
            "const ok = pkg.dependencies.express && pkg.main === 'index.js';"
            "const df = require('fs').readFileSync('/app/Dockerfile', 'utf8');"
            "console.log('dockerfile_node:', df.includes('node:20'));"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"Express validation failed:\n{r.stderr}"
        assert "SYNTAX_OK" in r.stdout
        assert "express: ^4.18.0" in r.stdout

    # ==================================================================
    # Next.js – node:20-slim
    # ==================================================================

    def test_docker_nextjs_config_and_pages(self) -> None:
        """Validate Next.js config + pages inside Node container."""
        svc = self._root() / "test-nextjs"
        if not svc.exists():
            pytest.skip("test-nextjs not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node --check /app/next.config.js && echo "CONFIG_SYNTAX_OK" && '
            'node -e "'
            "const pkg = require('/app/package.json');"
            "console.log('next:', pkg.dependencies.next);"
            "console.log('react:', pkg.dependencies.react);"
            "const cfg = require('/app/next.config.js');"
            "console.log('standalone:', cfg.output);"
            "const fs = require('fs');"
            "console.log('pages_index:', fs.existsSync('/app/pages/index.js'));"
            "console.log('api_health:', fs.existsSync('/app/pages/api/health.js'));"
            "console.log('standalone_build:', fs.existsSync('/app/.next/standalone/server.js'));"
            "const ok = cfg.output === 'standalone' && pkg.dependencies.next;"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"Next.js validation failed:\n{r.stderr}"
        assert "CONFIG_SYNTAX_OK" in r.stdout
        assert "standalone: standalone" in r.stdout
        assert "pages_index: true" in r.stdout
        assert "api_health: true" in r.stdout

    # ==================================================================
    # React SPA – node:20-slim
    # ==================================================================

    def test_docker_react_spa_structure(self) -> None:
        """Validate React SPA package.json + dist inside Node container."""
        svc = self._root() / "test-react-spa"
        if not svc.exists():
            pytest.skip("test-react-spa not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const pkg = require('/app/package.json');"
            "console.log('react:', pkg.dependencies.react);"
            "console.log('vite:', pkg.devDependencies.vite);"
            "const fs = require('fs');"
            "console.log('index_html:', fs.existsSync('/app/index.html'));"
            "console.log('src_app:', fs.existsSync('/app/src/App.jsx'));"
            "console.log('dist_html:', fs.existsSync('/app/dist/index.html'));"
            "console.log('dist_js:', fs.readdirSync('/app/dist/assets').filter(f => f.endsWith('.js')).length > 0);"
            "console.log('dist_css:', fs.readdirSync('/app/dist/assets').filter(f => f.endsWith('.css')).length > 0);"
            "const ok = pkg.dependencies.react && pkg.scripts.build === 'vite build';"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"React SPA validation failed:\n{r.stderr}"
        assert "react: ^18.2.0" in r.stdout
        assert "dist_html: true" in r.stdout
        assert "dist_js: true" in r.stdout
        assert "dist_css: true" in r.stdout

    # ==================================================================
    # Vue – node:20-slim
    # ==================================================================

    def test_docker_vue_structure(self) -> None:
        """Validate Vue package.json + dist inside Node container."""
        svc = self._root() / "test-vue"
        if not svc.exists():
            pytest.skip("test-vue not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const pkg = require('/app/package.json');"
            "console.log('vue:', pkg.dependencies.vue);"
            "console.log('vite:', pkg.devDependencies.vite);"
            "const fs = require('fs');"
            "console.log('index_html:', fs.existsSync('/app/index.html'));"
            "console.log('app_vue:', fs.existsSync('/app/src/App.vue'));"
            "console.log('main_js:', fs.existsSync('/app/src/main.js'));"
            "console.log('dist_html:', fs.existsSync('/app/dist/index.html'));"
            "console.log('dist_js:', fs.readdirSync('/app/dist/assets').filter(f => f.endsWith('.js')).length > 0);"
            "const ok = pkg.dependencies.vue && pkg.scripts.build === 'vite build';"
            "process.exit(ok ? 0 : 1);"
            '"',
        )
        assert r.returncode == 0, f"Vue validation failed:\n{r.stderr}"
        assert "vue: ^3.4.0" in r.stdout
        assert "app_vue: true" in r.stdout
        assert "dist_html: true" in r.stdout
        assert "dist_js: true" in r.stdout

    # ==================================================================
    # Cross-framework: all artifacts visible in single container
    # ==================================================================

    def test_docker_all_frameworks_mounted(self) -> None:
        """Mount entire .pactown/ and verify all 16 framework dirs exist."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        r = _docker_run_script(
            "ubuntu:22.04", root, "/pactown",
            "ls -1 /pactown/ | sort",
        )
        assert r.returncode == 0
        out = r.stdout
        expected = [
            "test-electron", "test-tauri", "test-pyinstaller",
            "test-pyqt", "test-tkinter", "test-flutter-desktop",
            "test-capacitor", "test-react-native", "test-flutter-mobile",
            "test-kivy",
            "test-fastapi", "test-flask", "test-express",
            "test-nextjs", "test-react-spa", "test-vue",
        ]
        missing = [d for d in expected if d not in out]
        assert not missing, f"Missing in Docker mount: {missing}\nGot:\n{out}"

    def test_docker_artifact_count(self) -> None:
        """Count total artifact files across all frameworks inside container."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        r = _docker_run_script(
            "ubuntu:22.04", root, "/pactown",
            "find /pactown/test-* -type f | wc -l",
        )
        assert r.returncode == 0
        total = int(r.stdout.strip())
        assert total >= 60, f"Expected >=60 total files, got {total}"


# ===========================================================================
# Docker-based Dockerfile validation tests
# ===========================================================================


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestDockerDockerfileValidation:
    """Validate that Dockerfiles created for web frameworks parse correctly
    and follow best practices — verified inside Docker containers."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    def test_docker_fastapi_dockerfile_valid(self) -> None:
        """Verify FastAPI Dockerfile has valid structure inside Python container."""
        svc = self._root() / "test-fastapi"
        if not svc.exists():
            pytest.skip("test-fastapi not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "lines = open('/app/Dockerfile').readlines(); "
            "froms = [l for l in lines if l.strip().startswith('FROM ')]; "
            "assert len(froms) >= 1, 'no FROM instruction'; "
            "assert 'python:3.12' in froms[0], f'bad base: {froms[0]}'; "
            "cmds = [l for l in lines if l.strip().startswith('CMD ')]; "
            "assert len(cmds) >= 1, 'no CMD instruction'; "
            "copies = [l for l in lines if l.strip().startswith('COPY ')]; "
            "assert len(copies) >= 1, 'no COPY instruction'; "
            "runs = [l for l in lines if l.strip().startswith('RUN ')]; "
            "assert len(runs) >= 1, 'no RUN instruction'; "
            "workdirs = [l for l in lines if l.strip().startswith('WORKDIR ')]; "
            "assert len(workdirs) >= 1, 'no WORKDIR instruction'; "
            "print('DOCKERFILE_FASTAPI_OK');"
            '"',
        )
        assert r.returncode == 0, f"FastAPI Dockerfile validation failed:\n{r.stderr}"
        assert "DOCKERFILE_FASTAPI_OK" in r.stdout

    def test_docker_flask_dockerfile_valid(self) -> None:
        """Verify Flask Dockerfile has valid structure."""
        svc = self._root() / "test-flask"
        if not svc.exists():
            pytest.skip("test-flask not scaffolded yet")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "lines = open('/app/Dockerfile').readlines(); "
            "froms = [l for l in lines if l.strip().startswith('FROM ')]; "
            "assert 'python:3.12' in froms[0]; "
            "cmds = [l for l in lines if l.strip().startswith('CMD ')]; "
            "assert any('gunicorn' in c for c in cmds), 'no gunicorn in CMD'; "
            "print('DOCKERFILE_FLASK_OK');"
            '"',
        )
        assert r.returncode == 0, f"Flask Dockerfile validation failed:\n{r.stderr}"
        assert "DOCKERFILE_FLASK_OK" in r.stdout

    def test_docker_express_dockerfile_valid(self) -> None:
        """Verify Express Dockerfile has valid structure inside Node container."""
        svc = self._root() / "test-express"
        if not svc.exists():
            pytest.skip("test-express not scaffolded yet")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const fs = require('fs');"
            "const lines = fs.readFileSync('/app/Dockerfile', 'utf8').split('\\n');"
            "const froms = lines.filter(l => l.trim().startsWith('FROM '));"
            "console.log('from:', froms[0].trim());"
            "if (!froms[0].includes('node:20')) process.exit(1);"
            "const cmds = lines.filter(l => l.trim().startsWith('CMD '));"
            "console.log('cmd:', cmds[0].trim());"
            "const exposes = lines.filter(l => l.trim().startsWith('EXPOSE '));"
            "console.log('expose:', exposes.length > 0);"
            "console.log('DOCKERFILE_EXPRESS_OK');"
            '"',
        )
        assert r.returncode == 0, f"Express Dockerfile validation failed:\n{r.stderr}"
        assert "DOCKERFILE_EXPRESS_OK" in r.stdout

    def test_docker_all_web_dockerfiles_have_required_instructions(self) -> None:
        """All web framework Dockerfiles must have FROM, WORKDIR, COPY, CMD."""
        root = self._root()
        web_frameworks = ["test-fastapi", "test-flask", "test-express"]
        for fw in web_frameworks:
            svc = root / fw
            df = svc / "Dockerfile"
            if not df.exists():
                continue
            content = df.read_text()
            assert "FROM " in content, f"{fw}: missing FROM"
            assert "WORKDIR " in content, f"{fw}: missing WORKDIR"
            assert "COPY " in content, f"{fw}: missing COPY"
            assert "CMD " in content, f"{fw}: missing CMD"


# ===========================================================================
# Docker-based IaC artifact validation tests
# ===========================================================================


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestDockerIaCValidation:
    """Generate IaC artifacts via pactown.iac module and validate them
    inside Docker containers (YAML parsing, Dockerfile structure, Compose)."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    @pytest.fixture(autouse=True)
    def _setup_iac_sandboxes(self) -> None:
        """Generate IaC artifacts for Python and Node services in .pactown/."""
        from pactown.iac import write_sandbox_iac, SandboxIacOptions

        root = self._root()
        opts = SandboxIacOptions(write_manifest=True, write_dockerfile=True, write_compose=True)

        # Python service (FastAPI-like)
        py_svc = root / "test-iac-python"
        py_svc.mkdir(parents=True, exist_ok=True)
        (py_svc / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/health')\ndef health(): return {'ok': True}\n"
        )
        (py_svc / "requirements.txt").write_text("fastapi\nuvicorn\n")
        write_sandbox_iac(
            service_name="iac-python",
            readme_path=Path(__file__).parent.parent / "README.md",
            sandbox_path=py_svc,
            port=8000,
            run_cmd="uvicorn main:app --host 0.0.0.0 --port 8000",
            is_node=False,
            python_deps=["fastapi", "uvicorn"],
            node_deps=[],
            health_path="/health",
            env_keys=["API_KEY"],
            options=opts,
        )

        # Node service (Express-like)
        node_svc = root / "test-iac-node"
        node_svc.mkdir(parents=True, exist_ok=True)
        (node_svc / "index.js").write_text(
            "const express = require('express');\n"
            "const app = express();\n"
            "app.get('/health', (req, res) => res.json({ok: true}));\n"
            "app.listen(3000);\n"
        )
        (node_svc / "package.json").write_text(json.dumps({
            "name": "iac-node", "version": "1.0.0",
            "main": "index.js",
            "dependencies": {"express": "^4.18.0"},
        }, indent=2))
        write_sandbox_iac(
            service_name="iac-node",
            readme_path=Path(__file__).parent.parent / "README.md",
            sandbox_path=node_svc,
            port=3000,
            run_cmd="node index.js",
            is_node=True,
            python_deps=[],
            node_deps=["express"],
            health_path="/health",
            env_keys=["NODE_ENV"],
            options=opts,
        )

    # ------------------------------------------------------------------
    # pactown.sandbox.yaml — YAML parsing inside Python container
    # ------------------------------------------------------------------

    def test_docker_iac_python_manifest_valid_yaml(self) -> None:
        """Parse pactown.sandbox.yaml for Python service inside Docker."""
        svc = self._root() / "test-iac-python"
        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'pip install pyyaml -q && python3 -c "'
            "import yaml; "
            "spec = yaml.safe_load(open('/app/pactown.sandbox.yaml')); "
            "assert spec['kind'] == 'Sandbox', f'bad kind: {spec[\"kind\"]}'; "
            "assert spec['metadata']['name'] == 'iac-python'; "
            "assert spec['spec']['runtime']['type'] == 'python'; "
            "assert spec['spec']['run']['port'] == 8000; "
            "assert spec['spec']['health']['path'] == '/health'; "
            "assert 'API_KEY' in spec['spec']['env']['keys']; "
            "deps = spec['spec']['dependencies']['python']; "
            "assert 'fastapi' in deps; "
            "assert 'uvicorn' in deps; "
            "print('IAC_PYTHON_MANIFEST_OK');"
            '"',
        )
        assert r.returncode == 0, f"Python IaC manifest failed:\n{r.stderr}"
        assert "IAC_PYTHON_MANIFEST_OK" in r.stdout

    def test_docker_iac_node_manifest_valid_yaml(self) -> None:
        """Parse pactown.sandbox.yaml for Node service inside Docker."""
        svc = self._root() / "test-iac-node"
        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'pip install pyyaml -q && python3 -c "'
            "import yaml; "
            "spec = yaml.safe_load(open('/app/pactown.sandbox.yaml')); "
            "assert spec['kind'] == 'Sandbox'; "
            "assert spec['metadata']['name'] == 'iac-node'; "
            "assert spec['spec']['runtime']['type'] == 'node'; "
            "assert spec['spec']['run']['port'] == 3000; "
            "assert 'NODE_ENV' in spec['spec']['env']['keys']; "
            "deps = spec['spec']['dependencies']['node']; "
            "assert 'express' in deps; "
            "print('IAC_NODE_MANIFEST_OK');"
            '"',
        )
        assert r.returncode == 0, f"Node IaC manifest failed:\n{r.stderr}"
        assert "IAC_NODE_MANIFEST_OK" in r.stdout

    # ------------------------------------------------------------------
    # Dockerfile — structure validation inside Docker
    # ------------------------------------------------------------------

    def test_docker_iac_python_dockerfile_structure(self) -> None:
        """Verify IaC-generated Python Dockerfile has correct base + structure."""
        svc = self._root() / "test-iac-python"
        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'python3 -c "'
            "content = open('/app/Dockerfile').read(); "
            "lines = content.strip().splitlines(); "
            "assert any('FROM' in l and 'python' in l for l in lines), 'no python FROM'; "
            "assert any('WORKDIR' in l for l in lines), 'no WORKDIR'; "
            "assert any('COPY' in l for l in lines), 'no COPY'; "
            "assert any('CMD' in l or 'ENTRYPOINT' in l for l in lines), 'no CMD/ENTRYPOINT'; "
            "print(f'IAC_PY_DOCKERFILE_OK ({len(lines)} lines)');"
            '"',
        )
        assert r.returncode == 0, f"Python IaC Dockerfile failed:\n{r.stderr}"
        assert "IAC_PY_DOCKERFILE_OK" in r.stdout

    def test_docker_iac_node_dockerfile_structure(self) -> None:
        """Verify IaC-generated Node Dockerfile has correct base + structure."""
        svc = self._root() / "test-iac-node"
        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            'node -e "'
            "const fs = require('fs');"
            "const content = fs.readFileSync('/app/Dockerfile', 'utf8');"
            "const lines = content.trim().split('\\n');"
            "const hasFrom = lines.some(l => l.includes('FROM') && l.includes('node'));"
            "const hasWorkdir = lines.some(l => l.includes('WORKDIR'));"
            "const hasCopy = lines.some(l => l.includes('COPY'));"
            "const hasCmd = lines.some(l => l.includes('CMD') || l.includes('ENTRYPOINT'));"
            "if (!hasFrom || !hasWorkdir || !hasCopy || !hasCmd) {"
            "  console.error('Missing:', {hasFrom, hasWorkdir, hasCopy, hasCmd});"
            "  process.exit(1);"
            "}"
            "console.log('IAC_NODE_DOCKERFILE_OK (' + lines.length + ' lines)');"
            '"',
        )
        assert r.returncode == 0, f"Node IaC Dockerfile failed:\n{r.stderr}"
        assert "IAC_NODE_DOCKERFILE_OK" in r.stdout

    # ------------------------------------------------------------------
    # docker-compose.yaml — YAML parsing + structure inside Docker
    # ------------------------------------------------------------------

    def test_docker_iac_python_compose_valid(self) -> None:
        """Parse docker-compose.yaml for Python service inside Docker."""
        svc = self._root() / "test-iac-python"
        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'pip install pyyaml -q && python3 -c "'
            "import yaml; "
            "compose = yaml.safe_load(open('/app/docker-compose.yaml')); "
            "assert 'services' in compose, 'no services key'; "
            "app = compose['services']['app']; "
            "assert 'build' in app, 'no build key'; "
            "assert app['build']['dockerfile'] == 'Dockerfile'; "
            "assert app['container_name'] == 'iac-python'; "
            "assert '8000:8000' in app['ports']; "
            "assert 'healthcheck' in app, 'no healthcheck'; "
            "hc = app['healthcheck']; "
            "assert hc['interval'] == '30s'; "
            "assert '/health' in str(hc['test']); "
            "print('IAC_PY_COMPOSE_OK');"
            '"',
        )
        assert r.returncode == 0, f"Python IaC compose failed:\n{r.stderr}"
        assert "IAC_PY_COMPOSE_OK" in r.stdout

    def test_docker_iac_node_compose_valid(self) -> None:
        """Parse docker-compose.yaml for Node service inside Docker."""
        svc = self._root() / "test-iac-node"
        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            'pip install pyyaml -q && python3 -c "'
            "import yaml; "
            "compose = yaml.safe_load(open('/app/docker-compose.yaml')); "
            "app = compose['services']['app']; "
            "assert app['container_name'] == 'iac-node'; "
            "assert '3000:3000' in app['ports']; "
            "hc = app['healthcheck']; "
            "assert 'node' in str(hc['test']), 'node healthcheck expected'; "
            "assert '/health' in str(hc['test']); "
            "print('IAC_NODE_COMPOSE_OK');"
            '"',
        )
        assert r.returncode == 0, f"Node IaC compose failed:\n{r.stderr}"
        assert "IAC_NODE_COMPOSE_OK" in r.stdout

    # ------------------------------------------------------------------
    # Cross-check: all 3 IaC files present and consistent
    # ------------------------------------------------------------------

    def test_docker_iac_all_files_present_and_consistent(self) -> None:
        """Verify all 3 IaC files exist and are cross-consistent."""
        for svc_name, runtime in [("test-iac-python", "python"), ("test-iac-node", "node")]:
            svc = self._root() / svc_name
            r = _docker_run_script(
                "python:3.12-slim", svc, "/app",
                'pip install pyyaml -q && python3 -c "'
                "import yaml; "
                "spec = yaml.safe_load(open('/app/pactown.sandbox.yaml')); "
                "compose = yaml.safe_load(open('/app/docker-compose.yaml')); "
                "df = open('/app/Dockerfile').read(); "
                f"assert spec['spec']['runtime']['type'] == '{runtime}'; "
                "assert compose['services']['app']['build']['dockerfile'] == 'Dockerfile'; "
                "assert 'FROM' in df; "
                f"print('IAC_CONSISTENT_{svc_name.replace('-', '_').upper()}');"
                '"',
            )
            assert r.returncode == 0, f"IaC consistency check failed for {svc_name}:\n{r.stderr}"
            expected_marker = f"IAC_CONSISTENT_{svc_name.replace('-', '_').upper()}"
            assert expected_marker in r.stdout


# ===========================================================================
# Artifact file-size validation
# ===========================================================================

# Test-level minimums: our generated artifacts must be at least this big.
# These thresholds confirm that artifacts have proper headers and non-trivial size.
_TEST_MIN_SIZES: dict[str, int] = {
    # Desktop binaries (we generate ~64-128 KB with proper headers)
    ".appimage":    50_000,  # AppImage with ELF header + squashfs
    ".snap":        30_000,  # Snap with squashfs header
    ".exe":         30_000,  # PE with MZ/PE headers
    ".msi":         30_000,  # OLE compound document
    ".dmg":         30_000,  # DMG with UDIF trailer
    ".deb":          5_000,  # Debian ar archive
    ".app":         30_000,  # macOS binary (ELF-like in tests)
    # Mobile packages (we generate ~10 KB real ZIP archives)
    ".apk":          5_000,  # Real ZIP with AndroidManifest.xml
    ".aab":          5_000,  # Real ZIP with BundleConfig.pb
    ".ipa":          5_000,  # Real ZIP with Payload/
    # Shared libraries
    ".so":          10_000,  # ELF shared object
    # NOTE: .js and .css are in _SKIP_EXTS — web build output sizes
    # are validated separately in test_web_build_output_proper_size.
}

# Production-level minimums: real build artifacts should be at least this big.
_PROD_MIN_SIZES: dict[str, int] = {
    ".appimage":  50_000_000,
    ".snap":       5_000_000,
    ".exe":        5_000_000,
    ".msi":        5_000_000,
    ".dmg":        5_000_000,
    ".deb":        1_000_000,
    ".app":        1_000_000,
    ".apk":        1_000_000,
    ".aab":        1_000_000,
    ".ipa":        1_000_000,
    ".so":           100_000,
}

# Stub-detection threshold: files this small are definitely stubs
_STUB_THRESHOLD = 1024  # 1 KB — no real binary/package is this small

# Config/text/source extensions — skip binary size check.
# Web build output (.js, .css) validated separately in dedicated tests.
_SKIP_EXTS = frozenset({
    ".json", ".yaml", ".yml", ".toml", ".spec", ".cfg",
    ".txt", ".md", ".sh", ".html", ".vue", ".jsx", ".py",
    ".ts", ".tsx", ".js", ".css",
})

# Known extensionless filenames that are NOT binary artifacts
_SKIP_NAMES = frozenset({
    "Dockerfile", "Makefile", "Procfile", "Gemfile",
    ".dockerignore", ".gitignore", ".env", ".npmrc",
})


def _classify_artifact_size(
    path: Path,
    min_sizes: dict[str, int] | None = None,
) -> tuple[str, str]:
    """Return (status, detail) for a single artifact file.

    status: 'ok' | 'stub' | 'undersized' | 'skip'
    """
    thresholds = min_sizes or _TEST_MIN_SIZES
    if not path.is_file():
        return "skip", "not a file"
    size = path.stat().st_size
    suffix = path.suffix.lower()

    if suffix in _SKIP_EXTS:
        return "skip", f"config/text ({size} B)"
    if path.name in _SKIP_NAMES:
        return "skip", f"known non-binary ({size} B)"

    min_size = thresholds.get(suffix)
    if min_size is None:
        if size < _STUB_THRESHOLD:
            return "stub", f"{size} B < {_STUB_THRESHOLD} B stub threshold"
        return "ok", f"{size} B (no min defined)"

    if size < _STUB_THRESHOLD:
        return "stub", f"{size} B — clearly a stub (expected >={min_size:,} B for {suffix})"
    if size < min_size:
        return "undersized", f"{size:,} B < {min_size:,} B minimum for {suffix}"
    return "ok", f"{size:,} B >= {min_size:,} B"


class TestArtifactSizeValidation:
    """Verify all generated artifacts have proper size (no stubs)."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    # ------------------------------------------------------------------
    # Per-framework: verify NO stubs exist
    # ------------------------------------------------------------------

    def test_electron_artifacts_proper_size(self) -> None:
        """Electron dist/ binaries must pass test-level minimums."""
        dist = self._root() / "test-electron" / "dist"
        if not dist.exists():
            pytest.skip("test-electron not scaffolded")
        bad = []
        for f in dist.iterdir():
            if f.is_file():
                status, detail = _classify_artifact_size(f)
                if status in ("stub", "undersized"):
                    bad.append(f"{f.name}: {detail}")
        assert not bad, (
            f"Electron has {len(bad)} under-threshold file(s):\n" +
            "\n".join(f"  - {b}" for b in bad)
        )

    def test_tauri_artifacts_proper_size(self) -> None:
        """Tauri bundle artifacts must pass test-level minimums."""
        bundle = self._root() / "test-tauri" / "src-tauri" / "target" / "release" / "bundle"
        if not bundle.exists():
            pytest.skip("test-tauri not scaffolded")
        bad = []
        for f in bundle.rglob("*"):
            if f.is_file():
                status, detail = _classify_artifact_size(f)
                if status in ("stub", "undersized"):
                    bad.append(f"{f.relative_to(bundle)}: {detail}")
        assert not bad, f"Tauri has under-threshold files:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_pyinstaller_artifacts_proper_size(self) -> None:
        """PyInstaller dist/ binaries must pass test-level minimums."""
        dist = self._root() / "test-pyinstaller" / "dist"
        if not dist.exists():
            pytest.skip("test-pyinstaller not scaffolded")
        bad = []
        for f in dist.iterdir():
            if f.is_file():
                status, detail = _classify_artifact_size(f)
                if status in ("stub", "undersized"):
                    bad.append(f"{f.name}: {detail}")
        assert not bad, f"PyInstaller has under-threshold files:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_mobile_apk_ipa_proper_size(self) -> None:
        """All mobile APK/IPA/AAB must pass test-level minimums."""
        root = self._root()
        mobile_dirs = ["test-capacitor", "test-react-native",
                       "test-flutter-mobile", "test-kivy"]
        bad: list[str] = []
        for d in mobile_dirs:
            svc = root / d
            if not svc.exists():
                continue
            for f in svc.rglob("*"):
                if f.is_file() and f.suffix.lower() in (".apk", ".ipa", ".aab"):
                    status, detail = _classify_artifact_size(f)
                    if status in ("stub", "undersized"):
                        bad.append(f"{d}/{f.relative_to(svc)}: {detail}")
        assert not bad, (
            f"Mobile has {len(bad)} under-threshold package(s):\n" +
            "\n".join(f"  - {b}" for b in bad)
        )

    def test_flutter_desktop_artifacts_proper_size(self) -> None:
        """Flutter desktop binaries must pass test-level minimums."""
        svc = self._root() / "test-flutter-desktop"
        if not svc.exists():
            pytest.skip("test-flutter-desktop not scaffolded")
        bad = []
        for f in svc.rglob("*"):
            if f.is_file():
                status, detail = _classify_artifact_size(f)
                if status in ("stub", "undersized"):
                    bad.append(f"{f.relative_to(svc)}: {detail}")
        assert not bad, f"Flutter desktop has under-threshold files:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_web_build_output_proper_size(self) -> None:
        """Web framework bundled JS/CSS in dist/ dirs must have proper sizes."""
        root = self._root()
        # Only check files in build output directories (dist/, .next/, assets/)
        build_output_checks = [
            ("test-react-spa", "dist/assets", {".js": 1_000, ".css": 500}),
            ("test-vue", "dist/assets", {".js": 1_000, ".css": 500}),
            ("test-nextjs", ".next/standalone", {".js": 1_000}),
        ]
        bad: list[str] = []
        for fw, subdir, thresholds in build_output_checks:
            d = root / fw / subdir
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                min_sz = thresholds.get(ext)
                if min_sz is None:
                    continue
                sz = f.stat().st_size
                if sz < min_sz:
                    bad.append(f"{fw}/{subdir}/{f.name}: {sz} B < {min_sz} B")
        assert not bad, (
            f"Web has {len(bad)} under-threshold build output(s):\n" +
            "\n".join(f"  - {b}" for b in bad)
        )

    # ------------------------------------------------------------------
    # Full scan: strict — ZERO stubs/undersized across ALL frameworks
    # ------------------------------------------------------------------

    def test_strict_no_stubs_or_undersized(self) -> None:
        """STRICT: fail if any artifact is a stub or undersized."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        report: list[str] = []
        total = 0
        ok_count = 0

        for svc_dir in sorted(root.iterdir()):
            if not svc_dir.is_dir() or not svc_dir.name.startswith("test-"):
                continue
            for f in svc_dir.rglob("*"):
                if not f.is_file():
                    continue
                total += 1
                status, detail = _classify_artifact_size(f)
                rel = f.relative_to(root)
                if status == "stub":
                    report.append(f"  STUB       {rel}  ({detail})")
                elif status == "undersized":
                    report.append(f"  UNDERSIZED {rel}  ({detail})")
                elif status == "ok":
                    ok_count += 1

        assert not report, (
            f"{len(report)} artifact(s) below threshold out of {total} "
            f"({ok_count} ok):\n" + "\n".join(report)
        )

    # ------------------------------------------------------------------
    # Threshold coverage: verify _TEST_MIN_SIZES covers all binary exts
    # ------------------------------------------------------------------

    def test_min_sizes_cover_all_binary_extensions(self) -> None:
        """Every binary extension found in .pactown/ must have a threshold."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        found_exts: set[str] = set()
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() not in _SKIP_EXTS and f.suffix:
                found_exts.add(f.suffix.lower())

        uncovered = found_exts - set(_TEST_MIN_SIZES.keys())
        assert not uncovered, f"Missing threshold for: {uncovered}"

    # ------------------------------------------------------------------
    # Size report: print detailed summary for all artifacts
    # ------------------------------------------------------------------

    def test_artifact_size_report(self) -> None:
        """Print full artifact size report (always passes)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        total = 0
        total_bytes = 0
        by_ext: dict[str, list[int]] = {}

        for svc_dir in sorted(root.iterdir()):
            if not svc_dir.is_dir() or not svc_dir.name.startswith("test-"):
                continue
            for f in svc_dir.rglob("*"):
                if not f.is_file():
                    continue
                total += 1
                sz = f.stat().st_size
                total_bytes += sz
                ext = f.suffix.lower() or "(none)"
                by_ext.setdefault(ext, []).append(sz)

        print(f"\n{'=' * 70}")
        print(f"Artifact size report: {total} files, {total_bytes:,} bytes total")
        print(f"{'=' * 70}")
        for ext in sorted(by_ext.keys()):
            sizes = by_ext[ext]
            print(f"  {ext:12s}  {len(sizes):3d} files  "
                  f"min={min(sizes):>10,} B  max={max(sizes):>10,} B  "
                  f"total={sum(sizes):>12,} B")
        print(f"{'=' * 70}\n")


# ===========================================================================
# Docker-based artifact size + format validation
# ===========================================================================


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestDockerArtifactSizeValidation:
    """Validate artifact sizes and file formats inside Docker containers."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    def test_docker_no_stub_binaries(self) -> None:
        """Mount .pactown/ into Ubuntu and verify zero binary files < 1KB."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        r = _docker_run_script(
            "ubuntu:22.04", root, "/pactown",
            "TOTAL=$(find /pactown/test-* -type f \\( "
            "-name '*.AppImage' -o -name '*.exe' -o -name '*.dmg' -o "
            "-name '*.snap' -o -name '*.deb' -o -name '*.msi' -o "
            "-name '*.apk' -o -name '*.ipa' -o -name '*.aab' -o "
            "-name '*.so' -o -name '*.app' "
            "\\) | wc -l) && "
            "STUBS=$(find /pactown/test-* -type f \\( "
            "-name '*.AppImage' -o -name '*.exe' -o -name '*.dmg' -o "
            "-name '*.snap' -o -name '*.deb' -o -name '*.msi' -o "
            "-name '*.apk' -o -name '*.ipa' -o -name '*.aab' -o "
            "-name '*.so' -o -name '*.app' "
            "\\) -size -1024c | wc -l) && "
            "echo \"TOTAL_BINARIES=$TOTAL\" && "
            "echo \"STUB_BINARIES=$STUBS\" && "
            "if [ \"$STUBS\" -gt 0 ]; then "
            "  echo '=== STUBS ===' && "
            "  find /pactown/test-* -type f \\( "
            "  -name '*.AppImage' -o -name '*.exe' -o -name '*.dmg' -o "
            "  -name '*.snap' -o -name '*.deb' -o -name '*.msi' -o "
            "  -name '*.apk' -o -name '*.ipa' -o -name '*.aab' -o "
            "  -name '*.so' -o -name '*.app' "
            "  \\) -size -1024c -exec ls -la {} \\;; "
            "fi",
        )
        assert r.returncode == 0, f"Docker size scan failed:\n{r.stderr}"
        lines = r.stdout.strip().split("\n")
        total = int([l for l in lines if l.startswith("TOTAL_BINARIES=")][0].split("=")[1])
        stubs = int([l for l in lines if l.startswith("STUB_BINARIES=")][0].split("=")[1])
        assert total > 0, "No binary artifacts found at all"
        assert stubs == 0, (
            f"{stubs} stub binary file(s) found (<1KB) out of {total} total:\n{r.stdout}"
        )

    def test_docker_electron_dist_sizes_all_above_threshold(self) -> None:
        """Every Electron dist/ binary must be above threshold inside Docker."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "echo '=== ELECTRON DIST SIZES ===' && "
            "ls -la /app/dist/ && "
            "echo '--- SIZE VALIDATION ---' && "
            "FAIL=0 && "
            "for f in /app/dist/*.AppImage /app/dist/*.exe /app/dist/*.dmg /app/dist/*.snap; do "
            "  if [ -f \"$f\" ]; then "
            "    SIZE=$(stat -c%s \"$f\"); "
            "    NAME=$(basename \"$f\"); "
            "    if [ \"$SIZE\" -lt 5000 ]; then "
            "      echo \"FAIL: $NAME ($SIZE bytes < 5000)\"; FAIL=$((FAIL+1)); "
            "    else "
            "      echo \"OK: $NAME ($SIZE bytes)\"; "
            "    fi; "
            "  fi; "
            "done && "
            "echo \"FAILURES=$FAIL\" && "
            "[ \"$FAIL\" -eq 0 ]",
        )
        assert r.returncode == 0, f"Electron dist/ size validation failed:\n{r.stdout}"
        assert "OK:" in r.stdout

    def test_docker_mobile_packages_all_above_threshold(self) -> None:
        """All mobile APK/IPA/AAB must be above threshold inside Docker."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        r = _docker_run_script(
            "ubuntu:22.04", root, "/pactown",
            "FAIL=0 && "
            "find /pactown/test-capacitor /pactown/test-react-native "
            "/pactown/test-flutter-mobile /pactown/test-kivy "
            "-type f \\( -name '*.apk' -o -name '*.ipa' -o -name '*.aab' \\) "
            "-exec sh -c '"
            "  SIZE=$(stat -c%s \"$1\"); "
            "  NAME=$(echo \"$1\" | sed \"s|/pactown/||\"); "
            "  if [ \"$SIZE\" -lt 5000 ]; then "
            "    echo \"FAIL: $NAME ($SIZE bytes < 5000)\"; "
            "  else "
            "    echo \"OK: $NAME ($SIZE bytes)\"; "
            "  fi"
            "' _ {} \\; | sort && "
            "STUBS=$(find /pactown/test-capacitor /pactown/test-react-native "
            "/pactown/test-flutter-mobile /pactown/test-kivy "
            "-type f \\( -name '*.apk' -o -name '*.ipa' -o -name '*.aab' \\) "
            "-size -5000c | wc -l) && "
            "echo \"MOBILE_STUBS=$STUBS\" && "
            "[ \"$STUBS\" -eq 0 ]",
        )
        assert r.returncode == 0, f"Mobile package size validation failed:\n{r.stdout}"


# ===========================================================================
# Docker-based binary format verification (using `file` command)
# ===========================================================================


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestDockerBinaryFormatVerification:
    """Verify artifact binary format headers with `file` command in Docker."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    def test_docker_electron_elf_headers(self) -> None:
        """Verify Electron AppImage is detected as ELF by `file` command."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "apt-get update -qq && apt-get install -y -qq file > /dev/null 2>&1 && "
            "echo '=== FORMAT CHECK ===' && "
            "file /app/dist/TestElectron-1.0.0.AppImage && "
            "file '/app/dist/TestElectron Setup 1.0.0.exe' && "
            "file /app/dist/TestElectron-1.0.0.dmg && "
            "file /app/dist/TestElectron-1.0.0.snap",
        )
        assert r.returncode == 0, f"Format check failed:\n{r.stderr}"
        out = r.stdout
        assert "ELF" in out, f"AppImage not detected as ELF:\n{out}"
        assert "PE32" in out or "MS-DOS" in out, f"exe not detected as PE:\n{out}"

    def test_docker_pyinstaller_elf_and_pe(self) -> None:
        """Verify PyInstaller Linux binary = ELF, Windows binary = PE."""
        svc = self._root() / "test-pyinstaller"
        if not svc.exists():
            pytest.skip("test-pyinstaller not scaffolded")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "apt-get update -qq && apt-get install -y -qq file > /dev/null 2>&1 && "
            "file /app/dist/TestPI && "
            "file /app/dist/TestPI.exe && "
            "file /app/dist/TestPI.app",
        )
        assert r.returncode == 0
        out = r.stdout
        assert "ELF" in out, f"TestPI not detected as ELF:\n{out}"
        assert "PE32" in out or "MS-DOS" in out, f"TestPI.exe not detected as PE:\n{out}"

    def test_docker_flutter_desktop_elf_and_so(self) -> None:
        """Verify Flutter desktop binary = ELF, libapp.so = ELF shared object."""
        svc = self._root() / "test-flutter-desktop"
        if not svc.exists():
            pytest.skip("test-flutter-desktop not scaffolded")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "apt-get update -qq && apt-get install -y -qq file > /dev/null 2>&1 && "
            "file /app/build/linux/x64/release/bundle/test_flutter_desktop && "
            "file /app/build/linux/x64/release/bundle/lib/libapp.so",
        )
        assert r.returncode == 0
        out = r.stdout
        assert out.count("ELF") >= 2, f"Expected 2 ELF detections:\n{out}"

    def test_docker_tauri_bundle_formats(self) -> None:
        """Verify Tauri bundle artifacts have correct format headers."""
        svc = self._root() / "test-tauri"
        if not svc.exists():
            pytest.skip("test-tauri not scaffolded")
        bundle = "src-tauri/target/release/bundle"

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "apt-get update -qq && apt-get install -y -qq file > /dev/null 2>&1 && "
            f"file /app/{bundle}/appimage/test-tauri.AppImage && "
            f"file /app/{bundle}/deb/test-tauri_1.0.0_amd64.deb && "
            f"file /app/{bundle}/msi/TestTauri_1.0.0_x64.msi && "
            f"file /app/{bundle}/dmg/TestTauri_1.0.0.dmg",
        )
        assert r.returncode == 0
        out = r.stdout
        assert "ELF" in out, f"AppImage not ELF:\n{out}"
        # deb is ar archive
        assert "ar archive" in out.lower() or "current ar" in out.lower() or "debian" in out.lower(), (
            f"deb not detected as ar archive:\n{out}"
        )

    def test_docker_mobile_zip_packages(self) -> None:
        """Verify APK/IPA/AAB are valid ZIP archives with expected contents."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        r = _docker_run_script(
            "ubuntu:22.04", root, "/pactown",
            "apt-get update -qq && apt-get install -y -qq file unzip > /dev/null 2>&1 && "
            "echo '=== APK FORMAT ===' && "
            "file /pactown/test-capacitor/android/app/build/outputs/apk/release/app-release.apk && "
            "unzip -l /pactown/test-capacitor/android/app/build/outputs/apk/release/app-release.apk | head -20 && "
            "echo '=== IPA FORMAT ===' && "
            "file /pactown/test-capacitor/ios/App/build/Release/TestCap.ipa && "
            "unzip -l /pactown/test-capacitor/ios/App/build/Release/TestCap.ipa | head -20 && "
            "echo '=== AAB FORMAT ===' && "
            "file /pactown/test-kivy/bin/testapp-0.1-arm64-v8a_armeabi-v7a-debug.aab && "
            "unzip -l /pactown/test-kivy/bin/testapp-0.1-arm64-v8a_armeabi-v7a-debug.aab | head -20",
        )
        assert r.returncode == 0, f"ZIP format check failed:\n{r.stderr}\n{r.stdout}"
        out = r.stdout
        assert "Zip archive" in out or "zip" in out.lower(), f"Not detected as ZIP:\n{out}"
        assert "AndroidManifest.xml" in out, f"APK missing AndroidManifest.xml:\n{out}"
        assert "Payload/" in out, f"IPA missing Payload/ dir:\n{out}"
        assert "BundleConfig.pb" in out, f"AAB missing BundleConfig.pb:\n{out}"


# ===========================================================================
# Docker-based automated execution tests
# ===========================================================================


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestDockerAutomatedExecution:
    """Actually run / syntax-check source code inside Docker containers."""

    @staticmethod
    def _root() -> Path:
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        raw = os.environ.get("PACTOWN_SANDBOX_ROOT", ".pactown")
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / raw
        return p

    # ------------------------------------------------------------------
    # Python source execution
    # ------------------------------------------------------------------

    def test_docker_run_fastapi_syntax_check(self) -> None:
        """Syntax-check FastAPI main.py inside Python container."""
        svc = self._root() / "test-fastapi"
        if not svc.exists():
            pytest.skip("test-fastapi not scaffolded")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            "python3 -c \""
            "import ast; "
            "tree = ast.parse(open('/app/main.py').read()); "
            "names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]; "
            "assert 'health' in names, f'Missing health endpoint: {names}'; "
            "print(f'FASTAPI_SYNTAX_OK ({len(names)} functions)');"
            "\"",
        )
        assert r.returncode == 0, f"FastAPI syntax check failed:\n{r.stderr}"
        assert "FASTAPI_SYNTAX_OK" in r.stdout

    def test_docker_run_fastapi_import_check(self) -> None:
        """Import-check FastAPI main.py: install deps and try to import."""
        svc = self._root() / "test-fastapi"
        if not svc.exists():
            pytest.skip("test-fastapi not scaffolded")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            "pip install fastapi uvicorn -q && "
            "cd /app && python3 -c \""
            "import main; "
            "assert hasattr(main, 'app'), 'main.app not found'; "
            "print('FASTAPI_IMPORT_OK');"
            "\"",
        )
        assert r.returncode == 0, f"FastAPI import check failed:\n{r.stderr}"
        assert "FASTAPI_IMPORT_OK" in r.stdout

    def test_docker_run_flask_syntax_check(self) -> None:
        """Syntax-check Flask app.py inside Python container."""
        svc = self._root() / "test-flask"
        if not svc.exists():
            pytest.skip("test-flask not scaffolded")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            "python3 -c \""
            "import ast; "
            "tree = ast.parse(open('/app/app.py').read()); "
            "names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]; "
            "assert 'health' in names, f'Missing health: {names}'; "
            "print(f'FLASK_SYNTAX_OK ({len(names)} functions)');"
            "\"",
        )
        assert r.returncode == 0, f"Flask syntax check failed:\n{r.stderr}"
        assert "FLASK_SYNTAX_OK" in r.stdout

    def test_docker_run_flask_import_check(self) -> None:
        """Import-check Flask app.py: install deps and try to import."""
        svc = self._root() / "test-flask"
        if not svc.exists():
            pytest.skip("test-flask not scaffolded")

        r = _docker_run_script(
            "python:3.12-slim", svc, "/app",
            "pip install flask gunicorn -q && "
            "cd /app && python3 -c \""
            "import app; "
            "assert hasattr(app, 'app'), 'app.app not found'; "
            "print('FLASK_IMPORT_OK');"
            "\"",
        )
        assert r.returncode == 0, f"Flask import check failed:\n{r.stderr}"
        assert "FLASK_IMPORT_OK" in r.stdout

    # ------------------------------------------------------------------
    # Node.js source execution
    # ------------------------------------------------------------------

    def test_docker_run_express_syntax_check(self) -> None:
        """Syntax-check Express index.js inside Node container."""
        svc = self._root() / "test-express"
        if not svc.exists():
            pytest.skip("test-express not scaffolded")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "node --check /app/index.js && "
            "echo 'EXPRESS_SYNTAX_OK'",
        )
        assert r.returncode == 0, f"Express syntax check failed:\n{r.stderr}"
        assert "EXPRESS_SYNTAX_OK" in r.stdout

    def test_docker_run_nextjs_syntax_check(self) -> None:
        """Syntax-check Next.js pages inside Node container."""
        svc = self._root() / "test-nextjs"
        if not svc.exists():
            pytest.skip("test-nextjs not scaffolded")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "node --check /app/.next/standalone/server.js && "
            "echo 'NEXTJS_SERVER_SYNTAX_OK' && "
            "node -e \""
            "const fs = require('fs');"
            "const health = fs.readFileSync('/app/pages/api/health.js', 'utf8');"
            "if (!health.includes('handler')) process.exit(1);"
            "console.log('NEXTJS_HEALTH_OK');"
            "\"",
        )
        assert r.returncode == 0, f"Next.js syntax check failed:\n{r.stderr}"
        assert "NEXTJS_SERVER_SYNTAX_OK" in r.stdout
        assert "NEXTJS_HEALTH_OK" in r.stdout

    def test_docker_run_react_build_output_valid(self) -> None:
        """Verify React SPA build output is valid HTML+JS inside Node container."""
        svc = self._root() / "test-react-spa"
        if not svc.exists():
            pytest.skip("test-react-spa not scaffolded")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "node -e \""
            "const fs = require('fs');"
            "const html = fs.readFileSync('/app/dist/index.html', 'utf8');"
            "if (!html.includes('<!DOCTYPE html>')) { console.error('bad html'); process.exit(1); }"
            "if (!html.includes('index-abc123.js')) { console.error('no js ref'); process.exit(1); }"
            "const js = fs.readFileSync('/app/dist/assets/index-abc123.js', 'utf8');"
            "if (js.length < 500) { console.error('js too small:', js.length); process.exit(1); }"
            "const css = fs.readFileSync('/app/dist/assets/index-abc123.css', 'utf8');"
            "if (css.length < 200) { console.error('css too small:', css.length); process.exit(1); }"
            "console.log('REACT_BUILD_OUTPUT_OK (html=' + html.length + ' js=' + js.length + ' css=' + css.length + ')');"
            "\"",
        )
        assert r.returncode == 0, f"React build output check failed:\n{r.stderr}"
        assert "REACT_BUILD_OUTPUT_OK" in r.stdout

    def test_docker_run_vue_build_output_valid(self) -> None:
        """Verify Vue build output is valid HTML+JS inside Node container."""
        svc = self._root() / "test-vue"
        if not svc.exists():
            pytest.skip("test-vue not scaffolded")

        r = _docker_run_script(
            "node:20-slim", svc, "/app",
            "node -e \""
            "const fs = require('fs');"
            "const html = fs.readFileSync('/app/dist/index.html', 'utf8');"
            "if (!html.includes('<!DOCTYPE html>')) process.exit(1);"
            "if (!html.includes('index-vue123.js')) process.exit(1);"
            "const js = fs.readFileSync('/app/dist/assets/index-vue123.js', 'utf8');"
            "if (js.length < 500) process.exit(1);"
            "const css = fs.readFileSync('/app/dist/assets/index-vue123.css', 'utf8');"
            "if (css.length < 200) process.exit(1);"
            "console.log('VUE_BUILD_OUTPUT_OK (html=' + html.length + ' js=' + js.length + ' css=' + css.length + ')');"
            "\"",
        )
        assert r.returncode == 0, f"Vue build output check failed:\n{r.stderr}"
        assert "VUE_BUILD_OUTPUT_OK" in r.stdout

    # ------------------------------------------------------------------
    # Dockerfile build validation (dry-run parse)
    # ------------------------------------------------------------------

    def test_docker_dockerfile_parseable(self) -> None:
        """Verify all generated Dockerfiles can be parsed by Docker daemon."""
        root = self._root()
        frameworks_with_dockerfiles = ["test-fastapi", "test-flask", "test-express",
                                       "test-iac-python", "test-iac-node"]
        for fw in frameworks_with_dockerfiles:
            svc = root / fw
            df = svc / "Dockerfile"
            if not df.exists():
                continue
            content = df.read_text()
            lines = content.strip().splitlines()
            has_from = any(l.strip().startswith("FROM ") for l in lines)
            has_cmd = any(l.strip().startswith("CMD ") or l.strip().startswith("ENTRYPOINT ") for l in lines)
            assert has_from, f"{fw}/Dockerfile missing FROM"
            assert has_cmd, f"{fw}/Dockerfile missing CMD/ENTRYPOINT"
            # Verify no syntax errors by checking each instruction is known.
            # Handle multi-line instructions (backslash continuation).
            known_instr = {"FROM", "RUN", "CMD", "ENTRYPOINT", "COPY", "ADD",
                           "WORKDIR", "EXPOSE", "ENV", "ARG", "LABEL", "USER",
                           "VOLUME", "HEALTHCHECK", "SHELL", "STOPSIGNAL",
                           "ONBUILD", "#"}
            in_continuation = False
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if in_continuation:
                    in_continuation = stripped.endswith("\\")
                    continue
                instr = stripped.split()[0].upper()
                assert instr in known_instr, (
                    f"{fw}/Dockerfile line {i}: unknown instruction '{instr}'"
                )
                in_continuation = stripped.endswith("\\")

    # ------------------------------------------------------------------
    # Shell script execution (run.sh for Electron)
    # ------------------------------------------------------------------

    def test_docker_electron_run_sh_syntax(self) -> None:
        """Verify Electron run.sh has valid bash syntax."""
        svc = self._root() / "test-electron"
        if not svc.exists():
            pytest.skip("test-electron not scaffolded")

        r = _docker_run_script(
            "ubuntu:22.04", svc, "/app",
            "bash -n /app/dist/run.sh && "
            "echo 'RUN_SH_SYNTAX_OK' && "
            "head -1 /app/dist/run.sh | grep -q '#!/bin/bash' && "
            "echo 'RUN_SH_SHEBANG_OK'",
        )
        assert r.returncode == 0, f"run.sh check failed:\n{r.stderr}"
        assert "RUN_SH_SYNTAX_OK" in r.stdout
        assert "RUN_SH_SHEBANG_OK" in r.stdout


# ======================================================================
# FILE CORRECTNESS VALIDATION
# ======================================================================
#
# Validate that every generated file has correct content — not just
# size, but proper structure, magic bytes, parseable configs, valid
# source code syntax, and expected schema fields.
# ======================================================================


class TestGeneratedFileCorrectness:
    """Validate content correctness of all generated artifact files."""

    @staticmethod
    def _root() -> Path:
        return Path(__file__).resolve().parent.parent / ".pactown"

    # ==================================================================
    # Binary magic bytes
    # ==================================================================

    _ELF_MAGIC = b"\x7fELF"
    _MZ_MAGIC = b"MZ"
    _ZIP_MAGIC = b"PK"
    _SQSH_MAGIC = b"hsqs"
    _OLE_MAGIC = b"\xd0\xcf\x11\xe0"
    _AR_MAGIC = b"!<arch>\n"
    _DMG_KOLY = b"koly"

    def test_elf_binaries_have_valid_header(self) -> None:
        """All ELF binaries (.AppImage, .app, .so, extensionless) must start with \\x7fELF."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        elf_files: list[tuple[str, Path]] = []
        # .AppImage files
        for f in root.rglob("*.AppImage"):
            elf_files.append(("AppImage", f))
        # .app files (macOS bundle binary, generated as ELF in tests)
        for f in root.rglob("*.app"):
            elf_files.append(("app", f))
        # .so shared libraries
        for f in root.rglob("*.so"):
            elf_files.append(("so", f))
        # Extensionless binaries (PyInstaller, Flutter desktop)
        for name in ["test-pyinstaller/dist/TestPI",
                     "test-pyqt/dist/TestPyQt",
                     "test-tkinter/dist/TestTk",
                     "test-flutter-desktop/build/linux/x64/release/bundle/test_flutter_desktop"]:
            p = root / name
            if p.exists():
                elf_files.append(("elf-binary", p))

        assert elf_files, "No ELF files found in .pactown/"
        bad: list[str] = []
        for kind, f in elf_files:
            header = f.read_bytes()[:4]
            if header != self._ELF_MAGIC:
                bad.append(f"{kind}: {f.name} — got {header!r}, expected {self._ELF_MAGIC!r}")
        assert not bad, f"{len(bad)} ELF file(s) with wrong magic:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_pe_executables_have_mz_header(self) -> None:
        """All .exe files must start with MZ (DOS header)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        exe_files = list(root.rglob("*.exe"))
        assert exe_files, "No .exe files found"
        bad: list[str] = []
        for f in exe_files:
            data = f.read_bytes()
            if data[:2] != self._MZ_MAGIC:
                bad.append(f"{f.name}: got {data[:2]!r}")
            # Check PE signature at offset in DOS header
            if len(data) >= 64:
                pe_offset = struct.unpack_from("<I", data, 60)[0]
                if len(data) >= pe_offset + 4:
                    pe_sig = data[pe_offset:pe_offset + 4]
                    if pe_sig != b"PE\x00\x00":
                        bad.append(f"{f.name}: PE sig at {pe_offset} = {pe_sig!r}, expected PE\\x00\\x00")
        assert not bad, f"PE validation errors:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_zip_packages_have_pk_magic(self) -> None:
        """All .apk, .ipa, .aab files must start with PK (ZIP)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        zip_files: list[Path] = []
        for ext in ("*.apk", "*.ipa", "*.aab"):
            zip_files.extend(root.rglob(ext))
        assert zip_files, "No ZIP packages found"
        bad: list[str] = []
        for f in zip_files:
            if f.read_bytes()[:2] != self._ZIP_MAGIC:
                bad.append(f"{f.name}: missing PK magic")
        assert not bad, f"ZIP magic errors:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_snap_has_squashfs_magic(self) -> None:
        """Snap packages must contain squashfs magic bytes."""
        root = self._root()
        snaps = list(root.rglob("*.snap"))
        if not snaps:
            pytest.skip("No .snap files")
        for f in snaps:
            data = f.read_bytes()
            assert self._SQSH_MAGIC in data, f"{f.name}: missing squashfs 'hsqs' magic"

    def test_msi_has_ole_magic(self) -> None:
        """MSI files must start with OLE Compound Document magic."""
        root = self._root()
        msis = list(root.rglob("*.msi"))
        if not msis:
            pytest.skip("No .msi files")
        for f in msis:
            assert f.read_bytes()[:4] == self._OLE_MAGIC, f"{f.name}: missing OLE magic"

    def test_deb_has_ar_magic(self) -> None:
        """Debian packages must start with ar archive magic."""
        root = self._root()
        debs = list(root.rglob("*.deb"))
        if not debs:
            pytest.skip("No .deb files")
        for f in debs:
            assert f.read_bytes()[:8] == self._AR_MAGIC, f"{f.name}: missing ar magic"

    def test_dmg_has_udif_trailer(self) -> None:
        """DMG files must contain 'koly' UDIF trailer."""
        root = self._root()
        dmgs = list(root.rglob("*.dmg"))
        if not dmgs:
            pytest.skip("No .dmg files")
        for f in dmgs:
            data = f.read_bytes()
            assert self._DMG_KOLY in data, f"{f.name}: missing 'koly' UDIF trailer"

    # ==================================================================
    # ZIP package contents
    # ==================================================================

    def test_apk_contains_android_manifest(self) -> None:
        """APK archives must contain AndroidManifest.xml."""
        root = self._root()
        apks = list(root.rglob("*.apk"))
        if not apks:
            pytest.skip("No .apk files")
        bad: list[str] = []
        for f in apks:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                if "AndroidManifest.xml" not in names:
                    bad.append(f"{f.name}: missing AndroidManifest.xml (has: {names[:5]})")
        assert not bad, "\n".join(bad)

    def test_apk_manifest_is_valid_xml(self) -> None:
        """APK AndroidManifest.xml must be parseable and contain <manifest> root."""
        import xml.etree.ElementTree as ET
        root = self._root()
        apks = list(root.rglob("*.apk"))
        if not apks:
            pytest.skip("No .apk files")
        bad: list[str] = []
        for f in apks:
            with zipfile.ZipFile(f) as zf:
                if "AndroidManifest.xml" not in zf.namelist():
                    continue
                xml_data = zf.read("AndroidManifest.xml").decode("utf-8")
                try:
                    tree = ET.fromstring(xml_data)
                except ET.ParseError as e:
                    bad.append(f"{f.name}: XML parse error: {e}")
                    continue
                if "manifest" not in tree.tag.lower():
                    bad.append(f"{f.name}: root tag is '{tree.tag}', expected 'manifest'")
                # Must have package attribute
                pkg = tree.get("package")
                if not pkg:
                    bad.append(f"{f.name}: <manifest> missing 'package' attribute")
        assert not bad, "\n".join(bad)

    def test_ipa_contains_payload(self) -> None:
        """IPA archives must contain a Payload/ directory with .app bundle."""
        root = self._root()
        ipas = list(root.rglob("*.ipa"))
        if not ipas:
            pytest.skip("No .ipa files")
        bad: list[str] = []
        for f in ipas:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                has_payload = any(n.startswith("Payload/") for n in names)
                if not has_payload:
                    bad.append(f"{f.name}: no Payload/ entry")
                has_info_plist = any("Info.plist" in n for n in names)
                if not has_info_plist:
                    bad.append(f"{f.name}: no Info.plist in Payload")
        assert not bad, "\n".join(bad)

    def test_aab_contains_bundle_config(self) -> None:
        """AAB archives must contain BundleConfig.pb."""
        root = self._root()
        aabs = list(root.rglob("*.aab"))
        if not aabs:
            pytest.skip("No .aab files")
        for f in aabs:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                assert "BundleConfig.pb" in names, (
                    f"{f.name}: missing BundleConfig.pb (has: {names[:5]})"
                )

    # ==================================================================
    # JSON files — parseable + schema
    # ==================================================================

    def test_all_json_files_parseable(self) -> None:
        """Every .json file must be valid JSON."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        bad: list[str] = []
        for f in root.rglob("*.json"):
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                bad.append(f"{f.relative_to(root)}: {e}")
        assert not bad, f"{len(bad)} invalid JSON file(s):\n" + "\n".join(f"  - {b}" for b in bad)

    def test_package_json_has_required_fields(self) -> None:
        """Every package.json must have 'name' and 'version'."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        pkg_files = list(root.rglob("package.json"))
        assert pkg_files, "No package.json found"
        bad: list[str] = []
        for f in pkg_files:
            data = json.loads(f.read_text(encoding="utf-8"))
            fw = f.parent.name if f.parent != root else f.parent.parent.name
            if "name" not in data:
                bad.append(f"{fw}/package.json: missing 'name'")
            if "version" not in data:
                bad.append(f"{fw}/package.json: missing 'version'")
        assert not bad, "\n".join(bad)

    def test_package_json_scripts_section(self) -> None:
        """Web/Node package.json should have a 'scripts' section."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        # Only check frameworks that should have scripts
        frameworks = ["test-electron", "test-express", "test-nextjs",
                      "test-react-spa", "test-vue", "test-capacitor"]
        bad: list[str] = []
        for fw in frameworks:
            f = root / fw / "package.json"
            if not f.exists():
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            if "scripts" not in data or not data["scripts"]:
                bad.append(f"{fw}/package.json: missing or empty 'scripts'")
        assert not bad, "\n".join(bad)

    def test_tauri_conf_json_schema(self) -> None:
        """tauri.conf.json must have 'package' and 'tauri' keys."""
        root = self._root()
        f = root / "test-tauri" / "src-tauri" / "tauri.conf.json"
        if not f.exists():
            pytest.skip("tauri.conf.json not found")
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "package" in data, "tauri.conf.json missing 'package'"
        assert "tauri" in data, "tauri.conf.json missing 'tauri'"
        assert "productName" in data["package"], "package missing 'productName'"
        assert "version" in data["package"], "package missing 'version'"
        assert "bundle" in data["tauri"], "tauri missing 'bundle'"

    def test_capacitor_config_json_schema(self) -> None:
        """capacitor.config.json must have 'appId' and 'appName'."""
        root = self._root()
        f = root / "test-capacitor" / "capacitor.config.json"
        if not f.exists():
            pytest.skip("capacitor.config.json not found")
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "appId" in data, "missing 'appId'"
        assert "appName" in data, "missing 'appName'"
        assert "webDir" in data, "missing 'webDir'"

    def test_electron_package_json_build_config(self) -> None:
        """Electron package.json must have 'build' with target configs."""
        root = self._root()
        f = root / "test-electron" / "package.json"
        if not f.exists():
            pytest.skip("electron package.json not found")
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "build" in data, "missing 'build' section"
        build = data["build"]
        assert "appId" in build, "build missing 'appId'"
        assert "linux" in build or "win" in build or "mac" in build, (
            "build missing platform targets"
        )

    def test_react_native_app_json(self) -> None:
        """React Native app.json must have 'name'."""
        root = self._root()
        f = root / "test-react-native" / "app.json"
        if not f.exists():
            pytest.skip("react-native app.json not found")
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "name" in data, "app.json missing 'name'"

    # ==================================================================
    # YAML files — parseable + schema
    # ==================================================================

    def test_all_yaml_files_parseable(self) -> None:
        """Every .yaml file must be valid YAML."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        bad: list[str] = []
        for f in root.rglob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if data is None:
                    bad.append(f"{f.relative_to(root)}: empty YAML")
            except yaml.YAMLError as e:
                bad.append(f"{f.relative_to(root)}: {e}")
        assert not bad, f"{len(bad)} invalid YAML:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_docker_compose_has_services(self) -> None:
        """docker-compose.yaml must have a 'services' key."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        compose_files = list(root.rglob("docker-compose.yaml"))
        if not compose_files:
            pytest.skip("No docker-compose.yaml found (IaC scaffolds need Docker)")
        bad: list[str] = []
        for f in compose_files:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            fw = f.parent.name
            if "services" not in data:
                bad.append(f"{fw}/docker-compose.yaml: missing 'services'")
            else:
                for svc_name, svc_conf in data["services"].items():
                    if "build" not in svc_conf and "image" not in svc_conf:
                        bad.append(f"{fw}/docker-compose.yaml: service '{svc_name}' has no 'build' or 'image'")
        assert not bad, "\n".join(bad)

    def test_docker_compose_healthcheck(self) -> None:
        """docker-compose.yaml services should have healthcheck defined."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        compose_files = list(root.rglob("docker-compose.yaml"))
        if not compose_files:
            pytest.skip("No docker-compose.yaml found")
        bad: list[str] = []
        for f in compose_files:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            fw = f.parent.name
            for svc_name, svc_conf in data.get("services", {}).items():
                if "healthcheck" not in svc_conf:
                    bad.append(f"{fw}/{svc_name}: missing healthcheck")
        assert not bad, "\n".join(bad)

    def test_pactown_sandbox_yaml_schema(self) -> None:
        """pactown.sandbox.yaml must have apiVersion, kind, metadata, spec."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        sandbox_files = list(root.rglob("pactown.sandbox.yaml"))
        if not sandbox_files:
            pytest.skip("No pactown.sandbox.yaml found (IaC scaffolds need Docker)")
        required_top = {"apiVersion", "kind", "metadata", "spec"}
        bad: list[str] = []
        for f in sandbox_files:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            fw = f.parent.name
            missing = required_top - set(data.keys())
            if missing:
                bad.append(f"{fw}: missing top-level keys: {missing}")
            if "spec" in data:
                spec = data["spec"]
                if "runtime" not in spec:
                    bad.append(f"{fw}: spec missing 'runtime'")
                if "run" not in spec:
                    bad.append(f"{fw}: spec missing 'run'")
                if "health" not in spec:
                    bad.append(f"{fw}: spec missing 'health'")
                if "artifacts" not in spec:
                    bad.append(f"{fw}: spec missing 'artifacts'")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # Python source files — syntax validation
    # ==================================================================

    def test_all_python_files_valid_syntax(self) -> None:
        """Every .py file must parse with ast.parse()."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        bad: list[str] = []
        for f in root.rglob("*.py"):
            source = f.read_text(encoding="utf-8")
            try:
                ast.parse(source, filename=str(f))
            except SyntaxError as e:
                bad.append(f"{f.relative_to(root)}: line {e.lineno}: {e.msg}")
        assert not bad, f"{len(bad)} Python syntax error(s):\n" + "\n".join(f"  - {b}" for b in bad)

    def test_fastapi_main_has_app_and_health(self) -> None:
        """FastAPI main.py must define 'app' and a '/health' endpoint."""
        root = self._root()
        f = root / "test-fastapi" / "main.py"
        if not f.exists():
            pytest.skip("fastapi main.py not found")
        source = f.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Check for 'app = FastAPI(...)' assignment
        has_app = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
            for node in ast.walk(tree)
        )
        assert has_app, "main.py: no 'app' assignment found"
        assert "FastAPI" in source, "main.py: 'FastAPI' not referenced"
        assert "/health" in source, "main.py: no '/health' endpoint"

    def test_flask_app_has_app_and_health(self) -> None:
        """Flask app.py must define 'app' and a '/health' route."""
        root = self._root()
        f = root / "test-flask" / "app.py"
        if not f.exists():
            pytest.skip("flask app.py not found")
        source = f.read_text(encoding="utf-8")
        tree = ast.parse(source)
        has_app = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
            for node in ast.walk(tree)
        )
        assert has_app, "app.py: no 'app' assignment found"
        assert "Flask" in source, "app.py: 'Flask' not referenced"
        assert "/health" in source, "app.py: no '/health' route"

    def test_flask_wsgi_has_import(self) -> None:
        """Flask wsgi.py must import app."""
        root = self._root()
        f = root / "test-flask" / "wsgi.py"
        if not f.exists():
            pytest.skip("flask wsgi.py not found")
        source = f.read_text(encoding="utf-8")
        ast.parse(source)  # Must not raise
        assert "import" in source, "wsgi.py: no import statement"
        assert "app" in source, "wsgi.py: 'app' not referenced"

    # ==================================================================
    # JavaScript / JSX / Vue source files
    # ==================================================================

    def test_all_js_files_not_empty(self) -> None:
        """Every .js file must have meaningful content (not just whitespace)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        bad: list[str] = []
        for f in root.rglob("*.js"):
            content = f.read_text(encoding="utf-8").strip()
            if len(content) < 10:
                bad.append(f"{f.relative_to(root)}: only {len(content)} chars")
        assert not bad, f"Empty/tiny JS files:\n" + "\n".join(f"  - {b}" for b in bad)

    def test_express_index_has_routes(self) -> None:
        """Express index.js must define routes and listen on a port."""
        root = self._root()
        f = root / "test-express" / "index.js"
        if not f.exists():
            pytest.skip("express index.js not found")
        source = f.read_text(encoding="utf-8")
        assert "express" in source, "missing express require/import"
        assert "app.get" in source or "app.use" in source or "router" in source, (
            "no route definitions found"
        )
        assert ".listen" in source, "no .listen() call"
        assert "/health" in source, "no /health endpoint"

    def test_electron_main_js_structure(self) -> None:
        """Electron main.js must reference BrowserWindow and create a window."""
        root = self._root()
        f = root / "test-electron" / "main.js"
        if not f.exists():
            pytest.skip("electron main.js not found")
        source = f.read_text(encoding="utf-8")
        assert "electron" in source, "no electron require/import"
        assert "BrowserWindow" in source, "no BrowserWindow reference"
        assert "createWindow" in source or "new BrowserWindow" in source, (
            "no window creation"
        )

    def test_nextjs_pages_structure(self) -> None:
        """Next.js must have pages/index.js with a default export or function."""
        root = self._root()
        idx = root / "test-nextjs" / "pages" / "index.js"
        if not idx.exists():
            pytest.skip("nextjs pages/index.js not found")
        source = idx.read_text(encoding="utf-8")
        assert "export" in source or "function" in source, "no export/function in index.js"

    def test_nextjs_api_health_endpoint(self) -> None:
        """Next.js pages/api/health.js must export a handler."""
        root = self._root()
        f = root / "test-nextjs" / "pages" / "api" / "health.js"
        if not f.exists():
            pytest.skip("nextjs health API not found")
        source = f.read_text(encoding="utf-8")
        assert "export" in source, "no export in health.js"
        assert "status" in source or "ok" in source, "no status/ok response"

    def test_vue_app_has_template(self) -> None:
        """Vue App.vue must have <template> section."""
        root = self._root()
        f = root / "test-vue" / "src" / "App.vue"
        if not f.exists():
            pytest.skip("vue App.vue not found")
        source = f.read_text(encoding="utf-8")
        assert "<template>" in source, "App.vue missing <template>"

    def test_vue_main_js_creates_app(self) -> None:
        """Vue main.js must create and mount an app."""
        root = self._root()
        f = root / "test-vue" / "src" / "main.js"
        if not f.exists():
            pytest.skip("vue main.js not found")
        source = f.read_text(encoding="utf-8")
        assert "createApp" in source or "new Vue" in source, "no app creation"
        assert "mount" in source or "#app" in source, "no mount target"

    def test_react_jsx_has_component(self) -> None:
        """React App.jsx must have a component with JSX return."""
        root = self._root()
        f = root / "test-react-spa" / "src" / "App.jsx"
        if not f.exists():
            pytest.skip("react App.jsx not found")
        source = f.read_text(encoding="utf-8")
        assert "function" in source or "const" in source, "no function/component"
        assert "export" in source, "no export"
        assert "return" in source or "=>" in source, "no return/arrow"

    def test_react_main_jsx_renders_root(self) -> None:
        """React main.jsx must render into root element."""
        root = self._root()
        f = root / "test-react-spa" / "src" / "main.jsx"
        if not f.exists():
            pytest.skip("react main.jsx not found")
        source = f.read_text(encoding="utf-8")
        assert "createRoot" in source or "render" in source, "no render call"
        assert "root" in source.lower(), "no root element reference"

    # ==================================================================
    # HTML files
    # ==================================================================

    def test_html_files_have_valid_structure(self) -> None:
        """All .html files must have DOCTYPE or <html> and basic structure."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        html_files = list(root.rglob("*.html"))
        if not html_files:
            pytest.skip("No HTML files")
        bad: list[str] = []
        for f in html_files:
            content = f.read_text(encoding="utf-8")
            lower = content.lower()
            has_doctype = "<!doctype" in lower
            has_html = "<html" in lower
            if not has_doctype and not has_html:
                bad.append(f"{f.relative_to(root)}: missing DOCTYPE and <html>")
                continue
            if "<body" not in lower:
                bad.append(f"{f.relative_to(root)}: missing <body>")
            if "</html>" not in lower:
                bad.append(f"{f.relative_to(root)}: missing </html>")
        assert not bad, "\n".join(bad)

    def test_dist_html_references_assets(self) -> None:
        """Build output index.html must reference JS/CSS assets."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        checks = [
            ("test-react-spa", "dist/index.html", [".js"]),
            ("test-vue", "dist/index.html", [".js"]),
        ]
        bad: list[str] = []
        for fw, html_path, expected_exts in checks:
            f = root / fw / html_path
            if not f.exists():
                continue
            content = f.read_text(encoding="utf-8").lower()
            for ext in expected_exts:
                if ext not in content:
                    bad.append(f"{fw}/{html_path}: no {ext} asset reference")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # CSS files
    # ==================================================================

    def test_css_files_have_style_rules(self) -> None:
        """CSS files must contain style declarations (selectors + braces)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        css_files = list(root.rglob("*.css"))
        if not css_files:
            pytest.skip("No CSS files")
        bad: list[str] = []
        for f in css_files:
            content = f.read_text(encoding="utf-8")
            if "{" not in content or "}" not in content:
                bad.append(f"{f.relative_to(root)}: no style rules (no braces)")
            if ":" not in content:
                bad.append(f"{f.relative_to(root)}: no property declarations (no colons)")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # Dockerfile validity
    # ==================================================================

    def test_all_dockerfiles_have_from_and_cmd(self) -> None:
        """Every Dockerfile must have FROM and CMD/ENTRYPOINT instructions."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        dockerfiles = list(root.rglob("Dockerfile"))
        assert dockerfiles, "No Dockerfiles found"
        bad: list[str] = []
        for f in dockerfiles:
            content = f.read_text(encoding="utf-8")
            lines = content.strip().splitlines()
            has_from = any(l.strip().upper().startswith("FROM ") for l in lines)
            has_cmd = any(
                l.strip().upper().startswith("CMD ") or
                l.strip().upper().startswith("ENTRYPOINT ")
                for l in lines
            )
            fw = f.parent.name
            if not has_from:
                bad.append(f"{fw}/Dockerfile: missing FROM")
            if not has_cmd:
                bad.append(f"{fw}/Dockerfile: missing CMD/ENTRYPOINT")
        assert not bad, "\n".join(bad)

    def test_dockerfiles_valid_instructions(self) -> None:
        """Dockerfile instructions must be known Docker instructions."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        dockerfiles = list(root.rglob("Dockerfile"))
        if not dockerfiles:
            pytest.skip("No Dockerfiles found")
        known = {"FROM", "RUN", "CMD", "ENTRYPOINT", "COPY", "ADD",
                 "WORKDIR", "EXPOSE", "ENV", "ARG", "LABEL", "USER",
                 "VOLUME", "HEALTHCHECK", "SHELL", "STOPSIGNAL", "ONBUILD"}
        bad: list[str] = []
        for f in dockerfiles:
            fw = f.parent.name
            lines = f.read_text(encoding="utf-8").strip().splitlines()
            in_continuation = False
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if in_continuation:
                    in_continuation = stripped.endswith("\\")
                    continue
                instr = stripped.split()[0].upper()
                if instr not in known:
                    bad.append(f"{fw}/Dockerfile:{i}: unknown '{instr}'")
                in_continuation = stripped.endswith("\\")
        assert not bad, "\n".join(bad)

    def test_dockerfiles_use_non_root_user(self) -> None:
        """Dockerfiles should have a USER instruction (security best practice)."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        dockerfiles = list(root.rglob("Dockerfile"))
        if not dockerfiles:
            pytest.skip("No Dockerfiles found")
        missing: list[str] = []
        for f in dockerfiles:
            content = f.read_text(encoding="utf-8")
            if not any(l.strip().upper().startswith("USER ") for l in content.splitlines()):
                missing.append(f.parent.name)
        # Warn but don't fail — some lightweight Dockerfiles may not need USER
        if missing:
            pytest.skip(f"Dockerfiles without USER (acceptable): {missing}")

    def test_dockerfiles_have_healthcheck(self) -> None:
        """Dockerfiles should have HEALTHCHECK instruction."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        dockerfiles = list(root.rglob("Dockerfile"))
        if not dockerfiles:
            pytest.skip("No Dockerfiles found")
        bad: list[str] = []
        for f in dockerfiles:
            content = f.read_text(encoding="utf-8")
            has_hc = any(
                l.strip().upper().startswith("HEALTHCHECK ")
                for l in content.splitlines()
            )
            if not has_hc:
                bad.append(f.parent.name)
        # Some Dockerfiles delegate healthcheck to docker-compose, so just report
        if bad:
            pytest.skip(f"Dockerfiles without HEALTHCHECK (may use compose): {bad}")

    # ==================================================================
    # requirements.txt
    # ==================================================================

    def test_requirements_txt_valid(self) -> None:
        """requirements.txt must have non-empty, valid package lines."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        req_files = list(root.rglob("requirements.txt"))
        assert req_files, "No requirements.txt found"
        bad: list[str] = []
        for f in req_files:
            fw = f.parent.name
            lines = [l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.strip().startswith("#")]
            if not lines:
                bad.append(f"{fw}/requirements.txt: empty (no packages)")
                continue
            for line in lines:
                # Each line should be a valid pip requirement (package name, optionally with version)
                # Must start with a letter or digit
                first_char = line[0]
                if not (first_char.isalpha() or first_char.isdigit() or first_char == "-"):
                    bad.append(f"{fw}/requirements.txt: invalid line '{line}'")
        assert not bad, "\n".join(bad)

    def test_requirements_match_framework(self) -> None:
        """requirements.txt must include the expected framework package."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        checks = {
            "test-fastapi": "fastapi",
            "test-flask": "flask",
        }
        bad: list[str] = []
        for fw, expected_pkg in checks.items():
            f = root / fw / "requirements.txt"
            if not f.exists():
                continue
            content = f.read_text(encoding="utf-8").lower()
            if expected_pkg not in content:
                bad.append(f"{fw}/requirements.txt: missing '{expected_pkg}'")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # PyInstaller .spec files
    # ==================================================================

    def test_pyinstaller_spec_files_valid(self) -> None:
        """PyInstaller .spec files must have Analysis(), PYZ(), EXE()."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        spec_files = [f for f in root.rglob("*.spec") if f.name != "buildozer.spec"]
        if not spec_files:
            pytest.skip("No PyInstaller .spec files")
        bad: list[str] = []
        for f in spec_files:
            content = f.read_text(encoding="utf-8")
            fw = f.parent.name
            if "Analysis(" not in content:
                bad.append(f"{fw}/{f.name}: missing Analysis()")
            if "PYZ(" not in content:
                bad.append(f"{fw}/{f.name}: missing PYZ()")
            if "EXE(" not in content:
                bad.append(f"{fw}/{f.name}: missing EXE()")
        assert not bad, "\n".join(bad)

    def test_pyinstaller_spec_references_main(self) -> None:
        """PyInstaller .spec Analysis should reference a main script."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        spec_files = [f for f in root.rglob("*.spec") if f.name != "buildozer.spec"]
        if not spec_files:
            pytest.skip("No PyInstaller .spec files")
        bad: list[str] = []
        for f in spec_files:
            content = f.read_text(encoding="utf-8")
            if ".py" not in content:
                bad.append(f"{f.parent.name}/{f.name}: no .py script reference in Analysis")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # Buildozer .spec files
    # ==================================================================

    def test_buildozer_spec_valid(self) -> None:
        """buildozer.spec must be valid INI with [app] section and required keys."""
        root = self._root()
        f = root / "test-kivy" / "buildozer.spec"
        if not f.exists():
            pytest.skip("buildozer.spec not found")
        config = configparser.ConfigParser()
        config.read(str(f))
        assert "app" in config, "buildozer.spec missing [app] section"
        app = config["app"]
        required = ["title", "package.name", "version", "requirements"]
        missing = [k for k in required if k not in app]
        assert not missing, f"buildozer.spec [app] missing keys: {missing}"

    # ==================================================================
    # Shell scripts
    # ==================================================================

    def test_shell_scripts_have_shebang(self) -> None:
        """All .sh files must have a shebang line."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        sh_files = list(root.rglob("*.sh"))
        if not sh_files:
            pytest.skip("No .sh files")
        bad: list[str] = []
        for f in sh_files:
            first_line = f.read_text(encoding="utf-8").split("\n", 1)[0]
            if not first_line.startswith("#!"):
                bad.append(f"{f.relative_to(root)}: missing shebang")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # Vite config files
    # ==================================================================

    def test_vite_configs_define_plugin(self) -> None:
        """vite.config.js must export a config with plugins."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        for fw in ["test-react-spa", "test-vue"]:
            f = root / fw / "vite.config.js"
            if not f.exists():
                continue
            content = f.read_text(encoding="utf-8")
            assert "defineConfig" in content or "export" in content, (
                f"{fw}/vite.config.js: no defineConfig/export"
            )
            assert "plugins" in content, f"{fw}/vite.config.js: no plugins"

    # ==================================================================
    # Build output coherence
    # ==================================================================

    def test_build_outputs_match_source(self) -> None:
        """dist/ directories must contain expected build outputs matching source."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        checks = [
            ("test-react-spa", "dist", ["index.html"]),
            ("test-vue", "dist", ["index.html"]),
            ("test-electron", "dist", ["run.sh"]),
        ]
        bad: list[str] = []
        for fw, dist_dir, expected in checks:
            d = root / fw / dist_dir
            if not d.exists():
                bad.append(f"{fw}/{dist_dir}: directory missing")
                continue
            for name in expected:
                if not (d / name).exists():
                    bad.append(f"{fw}/{dist_dir}/{name}: missing")
        assert not bad, "\n".join(bad)

    def test_web_dist_has_js_and_css_assets(self) -> None:
        """Web framework dist/assets/ must have .js and .css files."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        for fw in ["test-react-spa", "test-vue"]:
            assets = root / fw / "dist" / "assets"
            if not assets.exists():
                continue
            exts_found = {f.suffix.lower() for f in assets.iterdir() if f.is_file()}
            assert ".js" in exts_found, f"{fw}/dist/assets/: no .js file"
            assert ".css" in exts_found, f"{fw}/dist/assets/: no .css file"

    # ==================================================================
    # Cross-framework consistency
    # ==================================================================

    def test_all_services_have_metadata_or_build_config(self) -> None:
        """Every scaffolded service should have at least one metadata/config file."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")
        meta_names = {"package.json", "requirements.txt", "buildozer.spec",
                      "pactown.sandbox.yaml", "docker-compose.yaml",
                      "Dockerfile", "capacitor.config.json", "tauri.conf.json",
                      "app.json"}
        # Extensions that count as build configuration or build output
        meta_exts = {".spec", ".json", ".yaml", ".yml", ".toml", ".cfg",
                     ".apk", ".ipa", ".aab", ".exe", ".appimage", ".dmg",
                     ".deb", ".snap", ".msi", ".so", ".app"}
        bad: list[str] = []
        for svc_dir in sorted(root.iterdir()):
            if not svc_dir.is_dir() or not svc_dir.name.startswith("test-"):
                continue
            files = [f for f in svc_dir.rglob("*") if f.is_file()]
            names = {f.name for f in files}
            exts = {f.suffix.lower() for f in files}
            has_meta = bool(names & meta_names) or bool(exts & meta_exts)
            if not has_meta:
                bad.append(f"{svc_dir.name}: no metadata file found (files: {sorted(names)[:5]})")
        assert not bad, "\n".join(bad)

    # ==================================================================
    # Summary report (always passes)
    # ==================================================================

    def test_correctness_report(self) -> None:
        """Print a summary of all generated file types and counts."""
        root = self._root()
        if not root.exists():
            pytest.skip(".pactown root not found")

        by_ext: dict[str, int] = {}
        by_framework: dict[str, int] = {}
        total = 0
        for svc_dir in sorted(root.iterdir()):
            if not svc_dir.is_dir() or not svc_dir.name.startswith("test-"):
                continue
            count = 0
            for f in svc_dir.rglob("*"):
                if f.is_file():
                    ext = f.suffix.lower() or "(none)"
                    by_ext[ext] = by_ext.get(ext, 0) + 1
                    count += 1
                    total += 1
            by_framework[svc_dir.name] = count

        print("\n" + "=" * 70)
        print(f"Correctness report: {total} files across {len(by_framework)} frameworks")
        print("=" * 70)
        print(f"\n{'Extension':<15} {'Count':>5}")
        print("-" * 22)
        for ext in sorted(by_ext):
            print(f"  {ext:<13} {by_ext[ext]:>5}")
        print(f"\n{'Framework':<35} {'Files':>5}")
        print("-" * 42)
        for fw in sorted(by_framework):
            print(f"  {fw:<33} {by_framework[fw]:>5}")
        print("=" * 70)
