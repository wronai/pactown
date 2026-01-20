"""Configuration models for pactown ecosystems."""

import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class DependencyConfig:
    """Configuration for a service dependency."""
    name: str
    version: str = "*"
    registry: str = "local"
    endpoint: Optional[str] = None
    env_var: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict | str) -> "DependencyConfig":
        if isinstance(data, str):
            parts = data.split("@")
            name = parts[0]
            version = parts[1] if len(parts) > 1 else "*"
            return cls(name=name, version=version)
        return cls(**data)


@dataclass
class ServiceConfig:
    """Configuration for a single service in the ecosystem."""
    name: str
    readme: str
    port: Optional[int] = None
    env: dict[str, str] = field(default_factory=dict)
    depends_on: list[DependencyConfig] = field(default_factory=list)
    health_check: Optional[str] = None
    replicas: int = 1
    sandbox_path: Optional[str] = None
    auto_restart: bool = True
    timeout: int = 60

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "ServiceConfig":
        deps = []
        for dep in data.get("depends_on", []):
            deps.append(DependencyConfig.from_dict(dep))

        return cls(
            name=name,
            readme=data.get("readme", f"{name}/README.md"),
            port=data.get("port"),
            env=data.get("env", {}),
            depends_on=deps,
            health_check=data.get("health_check"),
            replicas=data.get("replicas", 1),
            sandbox_path=data.get("sandbox_path"),
            auto_restart=data.get("auto_restart", True),
            timeout=data.get("timeout", 60),
        )


@dataclass
class RegistryConfig:
    """Configuration for artifact registry."""
    url: str = "http://localhost:8800"
    auth_token: Optional[str] = None
    namespace: str = "default"


@dataclass
class CacheConfig:
    pip_index_url: Optional[str] = None
    pip_extra_index_url: Optional[str] = None
    pip_trusted_host: Optional[str] = None
    pip_default_timeout: Optional[str] = None
    pip_retries: Optional[str] = None
    npm_registry_url: Optional[str] = None
    apt_proxy: Optional[str] = None
    docker_registry_mirror: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "CacheConfig":
        src = env or os.environ

        def clean(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            v = str(value).strip()
            return v or None

        return cls(
            pip_index_url=clean(src.get("PACTOWN_PIP_INDEX_URL") or src.get("PIP_INDEX_URL")),
            pip_extra_index_url=clean(src.get("PACTOWN_PIP_EXTRA_INDEX_URL") or src.get("PIP_EXTRA_INDEX_URL")),
            pip_trusted_host=clean(src.get("PACTOWN_PIP_TRUSTED_HOST") or src.get("PIP_TRUSTED_HOST")),
            pip_default_timeout=clean(
                src.get("PACTOWN_PIP_DEFAULT_TIMEOUT")
                or src.get("PIP_DEFAULT_TIMEOUT")
                or src.get("PACTOWN_PIP_TIMEOUT")
                or src.get("PIP_TIMEOUT")
            ),
            pip_retries=clean(src.get("PACTOWN_PIP_RETRIES") or src.get("PIP_RETRIES")),
            npm_registry_url=clean(src.get("PACTOWN_NPM_REGISTRY_URL") or src.get("NPM_CONFIG_REGISTRY")),
            apt_proxy=clean(src.get("PACTOWN_APT_PROXY") or src.get("APT_PROXY")),
            docker_registry_mirror=clean(
                src.get("PACTOWN_DOCKER_REGISTRY_MIRROR") or src.get("DOCKER_REGISTRY_MIRROR")
            ),
        )

    def to_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.pip_index_url:
            env["PIP_INDEX_URL"] = self.pip_index_url
            if not self.pip_extra_index_url:
                env["PIP_EXTRA_INDEX_URL"] = self.pip_index_url
        if self.pip_extra_index_url:
            env["PIP_EXTRA_INDEX_URL"] = self.pip_extra_index_url
        if self.pip_trusted_host:
            env["PIP_TRUSTED_HOST"] = self.pip_trusted_host
        if self.pip_default_timeout:
            env["PIP_DEFAULT_TIMEOUT"] = str(self.pip_default_timeout)
        if self.pip_retries:
            env["PIP_RETRIES"] = str(self.pip_retries)
        if self.npm_registry_url:
            env["NPM_CONFIG_REGISTRY"] = self.npm_registry_url
        if self.apt_proxy:
            env["ACQUIRE::HTTP::PROXY"] = self.apt_proxy
            env["ACQUIRE::HTTPS::PROXY"] = self.apt_proxy
        if self.docker_registry_mirror:
            env["DOCKER_REGISTRY_MIRROR"] = self.docker_registry_mirror
        return env

    def to_docker_build_args(self) -> dict[str, str]:
        args: dict[str, str] = {}
        if self.pip_index_url:
            args["PIP_INDEX_URL"] = self.pip_index_url
            if not self.pip_extra_index_url:
                args["PIP_EXTRA_INDEX_URL"] = self.pip_index_url
        if self.pip_extra_index_url:
            args["PIP_EXTRA_INDEX_URL"] = self.pip_extra_index_url
        if self.pip_trusted_host:
            args["PIP_TRUSTED_HOST"] = self.pip_trusted_host
        if self.pip_default_timeout:
            args["PIP_DEFAULT_TIMEOUT"] = str(self.pip_default_timeout)
        if self.pip_retries:
            args["PIP_RETRIES"] = str(self.pip_retries)
        if self.npm_registry_url:
            args["NPM_CONFIG_REGISTRY"] = self.npm_registry_url
        if self.apt_proxy:
            args["APT_PROXY"] = self.apt_proxy
        if self.docker_registry_mirror:
            args["DOCKER_REGISTRY_MIRROR"] = self.docker_registry_mirror
        return args


@dataclass
class EcosystemConfig:
    """Configuration for a complete pactown ecosystem."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    services: dict[str, ServiceConfig] = field(default_factory=dict)
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    base_port: int = 8000
    sandbox_root: str = "./.pactown-sandboxes"
    network: str = "pactown-net"

    @classmethod
    def from_yaml(cls, path: Path) -> "EcosystemConfig":
        """Load ecosystem configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data, base_path=path.parent)

    @classmethod
    def from_dict(cls, data: dict, base_path: Optional[Path] = None) -> "EcosystemConfig":
        """Create configuration from dictionary."""
        services = {}
        base_port = data.get("base_port", 8000)

        for i, (name, svc_data) in enumerate(data.get("services", {}).items()):
            if svc_data.get("port") is None:
                svc_data["port"] = base_port + i
            services[name] = ServiceConfig.from_dict(name, svc_data)

        registry_data = data.get("registry", {})
        registry = RegistryConfig(
            url=registry_data.get("url", "http://localhost:8800"),
            auth_token=registry_data.get("auth_token"),
            namespace=registry_data.get("namespace", "default"),
        )

        return cls(
            name=data.get("name", "unnamed-ecosystem"),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            services=services,
            registry=registry,
            base_port=base_port,
            sandbox_root=data.get("sandbox_root", "./.pactown-sandboxes"),
            network=data.get("network", "pactown-net"),
        )

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "base_port": self.base_port,
            "sandbox_root": self.sandbox_root,
            "network": self.network,
            "registry": {
                "url": self.registry.url,
                "namespace": self.registry.namespace,
            },
            "services": {
                name: {
                    "readme": svc.readme,
                    "port": svc.port,
                    "env": svc.env,
                    "depends_on": [
                        {"name": d.name, "version": d.version, "endpoint": d.endpoint}
                        for d in svc.depends_on
                    ],
                    "health_check": svc.health_check,
                    "replicas": svc.replicas,
                }
                for name, svc in self.services.items()
            },
        }

    def to_yaml(self, path: Path) -> None:
        """Save configuration to YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)


def load_config(path: str | Path) -> EcosystemConfig:
    """Load ecosystem configuration from file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return EcosystemConfig.from_yaml(path)
