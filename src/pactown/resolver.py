"""Dependency resolver for pactown ecosystems."""

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .config import EcosystemConfig, ServiceConfig


@dataclass
class ResolvedDependency:
    """A resolved dependency with endpoint information."""
    name: str
    version: str
    endpoint: str
    env_var: str
    service: Optional[ServiceConfig] = None


class DependencyResolver:
    """Resolves dependencies between services in an ecosystem."""

    def __init__(self, config: EcosystemConfig):
        self.config = config
        self._graph: dict[str, list[str]] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        """Build dependency graph from configuration."""
        for name, service in self.config.services.items():
            self._graph[name] = []
            for dep in service.depends_on:
                if dep.name in self.config.services:
                    self._graph[name].append(dep.name)

    def get_startup_order(self) -> list[str]:
        """
        Get services in topological order for startup.
        Services with no dependencies start first.
        """
        # in_degree[X] = number of dependencies X has
        in_degree = {name: len(deps) for name, deps in self._graph.items()}

        # Start with services that have no dependencies
        queue = deque([name for name, degree in in_degree.items() if degree == 0])
        order = []

        while queue:
            current = queue.popleft()
            order.append(current)

            # For each service that depends on current, decrease its in_degree
            for name, deps in self._graph.items():
                if current in deps:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        if len(order) != len(self._graph):
            missing = set(self._graph.keys()) - set(order)
            raise ValueError(f"Circular dependency detected involving: {missing}")

        return order

    def get_shutdown_order(self) -> list[str]:
        """Get services in reverse order for shutdown."""
        return list(reversed(self.get_startup_order()))

    def resolve_service_deps(self, service_name: str) -> list[ResolvedDependency]:
        """Resolve all dependencies for a service."""
        if service_name not in self.config.services:
            raise ValueError(f"Unknown service: {service_name}")

        service = self.config.services[service_name]
        resolved = []

        for dep in service.depends_on:
            if dep.name in self.config.services:
                dep_service = self.config.services[dep.name]
                endpoint = dep.endpoint or f"http://localhost:{dep_service.port}"
                env_var = dep.env_var or f"{dep.name.upper().replace('-', '_')}_URL"

                resolved.append(ResolvedDependency(
                    name=dep.name,
                    version=dep.version,
                    endpoint=endpoint,
                    env_var=env_var,
                    service=dep_service,
                ))
            else:
                endpoint = dep.endpoint or f"http://localhost:8800/v1/{dep.name}"
                env_var = dep.env_var or f"{dep.name.upper().replace('-', '_')}_URL"

                resolved.append(ResolvedDependency(
                    name=dep.name,
                    version=dep.version,
                    endpoint=endpoint,
                    env_var=env_var,
                ))

        return resolved

    def get_environment(self, service_name: str) -> dict[str, str]:
        """Get environment variables for a service including dependency endpoints."""
        if service_name not in self.config.services:
            raise ValueError(f"Unknown service: {service_name}")

        service = self.config.services[service_name]
        env = dict(service.env)

        for dep in self.resolve_service_deps(service_name):
            env[dep.env_var] = dep.endpoint

        env["PACTOWN_SERVICE_NAME"] = service_name
        env["PACTOWN_ECOSYSTEM"] = self.config.name
        if service.port:
            env["MARKPACT_PORT"] = str(service.port)

        return env

    def validate(self) -> list[str]:
        """Validate the dependency graph and return any issues."""
        issues = []

        try:
            self.get_startup_order()
        except ValueError as e:
            issues.append(str(e))

        for name, service in self.config.services.items():
            for dep in service.depends_on:
                if dep.name not in self.config.services:
                    if dep.registry == "local":
                        issues.append(
                            f"Service '{name}' depends on '{dep.name}' which is not "
                            f"defined locally and no registry is configured"
                        )

        return issues

    def print_graph(self) -> str:
        """Return ASCII representation of dependency graph."""
        lines = [f"Ecosystem: {self.config.name}", ""]

        try:
            order = self.get_startup_order()
        except ValueError:
            order = list(self._graph.keys())

        for name in order:
            service = self.config.services[name]
            deps = [d.name for d in service.depends_on]
            port = f":{service.port}" if service.port else ""

            if deps:
                lines.append(f"  [{name}{port}] → {', '.join(deps)}")
            else:
                lines.append(f"  [{name}{port}] (no deps)")

        return "\n".join(lines)
