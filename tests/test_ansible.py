"""Tests for pactown.deploy.ansible – Ansible deployment backend."""

import json
import subprocess
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
