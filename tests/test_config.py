"""Tests for pactown configuration."""

import tempfile
from pathlib import Path

import pytest

from pactown.config import (
    CacheConfig,
    DependencyConfig,
    EcosystemConfig,
    RegistryConfig,
    ServiceConfig,
    load_config,
)


def test_dependency_config_from_string():
    dep = DependencyConfig.from_dict("my-service@1.0.0")
    assert dep.name == "my-service"
    assert dep.version == "1.0.0"


def test_dependency_config_from_dict():
    dep = DependencyConfig.from_dict({
        "name": "api",
        "version": "2.0.0",
        "endpoint": "http://localhost:8001",
        "env_var": "API_URL",
    })
    assert dep.name == "api"
    assert dep.version == "2.0.0"
    assert dep.endpoint == "http://localhost:8001"
    assert dep.env_var == "API_URL"


def test_service_config_from_dict():
    service = ServiceConfig.from_dict("web", {
        "readme": "services/web/README.md",
        "port": 8002,
        "health_check": "/health",
        "depends_on": [
            {"name": "api", "endpoint": "http://localhost:8001"},
        ],
    })
    assert service.name == "web"
    assert service.readme == "services/web/README.md"
    assert service.port == 8002
    assert service.health_check == "/health"
    assert len(service.depends_on) == 1
    assert service.depends_on[0].name == "api"


def test_ecosystem_config_from_dict():
    config = EcosystemConfig.from_dict({
        "name": "test-ecosystem",
        "version": "1.0.0",
        "services": {
            "api": {"readme": "api/README.md", "port": 8001},
            "web": {"readme": "web/README.md", "port": 8002},
        },
    })
    assert config.name == "test-ecosystem"
    assert config.version == "1.0.0"
    assert len(config.services) == 2
    assert "api" in config.services
    assert "web" in config.services


def test_ecosystem_config_auto_port():
    config = EcosystemConfig.from_dict({
        "name": "test",
        "base_port": 9000,
        "services": {
            "svc1": {"readme": "a/README.md"},
            "svc2": {"readme": "b/README.md"},
        },
    })
    assert config.services["svc1"].port == 9000
    assert config.services["svc2"].port == 9001


def test_ecosystem_config_from_yaml():
    yaml_content = """
name: yaml-test
version: 0.2.0
base_port: 8000
services:
  api:
    readme: api/README.md
    port: 8001
    health_check: /health
  web:
    readme: web/README.md
    port: 8002
    depends_on:
      - name: api
        endpoint: http://localhost:8001
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        f.flush()

        config = EcosystemConfig.from_yaml(Path(f.name))

    assert config.name == "yaml-test"
    assert config.version == "0.2.0"
    assert len(config.services) == 2
    assert config.services["web"].depends_on[0].name == "api"


def test_ecosystem_config_to_dict():
    config = EcosystemConfig(
        name="test",
        version="1.0.0",
        services={
            "api": ServiceConfig(name="api", readme="api/README.md", port=8001),
        },
    )
    data = config.to_dict()
    assert data["name"] == "test"
    assert "api" in data["services"]


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path.yaml")


def test_registry_config_defaults():
    config = RegistryConfig()
    assert config.url == "http://localhost:8800"
    assert config.namespace == "default"
    assert config.auth_token is None


def test_cache_config_from_env_prefers_pactown_prefixed_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "http://global/simple")
    monkeypatch.setenv("PACTOWN_PIP_INDEX_URL", "http://pactown/simple")
    monkeypatch.setenv("PACTOWN_NPM_REGISTRY_URL", "http://npm.local")

    cfg = CacheConfig.from_env()
    assert cfg.pip_index_url == "http://pactown/simple"
    assert cfg.npm_registry_url == "http://npm.local"


def test_cache_config_to_env_sets_pip_extra_when_missing() -> None:
    cfg = CacheConfig(pip_index_url="http://proxy/simple")
    env = cfg.to_env()
    assert env["PIP_INDEX_URL"] == "http://proxy/simple"
    assert env["PIP_EXTRA_INDEX_URL"] == "http://proxy/simple"


def test_cache_config_to_docker_build_args_maps_apt_proxy() -> None:
    cfg = CacheConfig(
        pip_index_url="http://pypi-proxy/simple",
        apt_proxy="http://apt-proxy:3142",
        npm_registry_url="http://verdaccio:4873",
    )
    args = cfg.to_docker_build_args()
    assert args["PIP_INDEX_URL"] == "http://pypi-proxy/simple"
    assert args["APT_PROXY"] == "http://apt-proxy:3142"
    assert args["NPM_CONFIG_REGISTRY"] == "http://verdaccio:4873"


def test_cache_config_from_env_reads_pip_timeout_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIP_DEFAULT_TIMEOUT", "15")
    monkeypatch.setenv("PIP_RETRIES", "2")
    monkeypatch.setenv("PACTOWN_PIP_DEFAULT_TIMEOUT", "60")
    monkeypatch.setenv("PACTOWN_PIP_RETRIES", "5")

    cfg = CacheConfig.from_env()
    assert cfg.pip_default_timeout == "60"
    assert cfg.pip_retries == "5"


def test_cache_config_to_env_includes_timeout_and_retries() -> None:
    cfg = CacheConfig(pip_default_timeout="45", pip_retries="4")
    env = cfg.to_env()
    assert env["PIP_DEFAULT_TIMEOUT"] == "45"
    assert env["PIP_RETRIES"] == "4"


def test_cache_config_to_docker_build_args_includes_timeout_and_retries() -> None:
    cfg = CacheConfig(pip_default_timeout="45", pip_retries="4")
    args = cfg.to_docker_build_args()
    assert args["PIP_DEFAULT_TIMEOUT"] == "45"
    assert args["PIP_RETRIES"] == "4"
