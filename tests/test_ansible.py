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
