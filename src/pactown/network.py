"""Network management for pactown - dynamic ports and service discovery."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional


@dataclass
class ServiceEndpoint:
    """Represents a running service's network endpoint."""
    name: str
    host: str
    port: int
    health_check: Optional[str] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> Optional[str]:
        if self.health_check:
            return f"{self.url}{self.health_check}"
        return None


# Minimum safe port - below this are privileged/system ports
MIN_SAFE_PORT = 1024


class PortAllocator:
    """Allocates free ports dynamically.
    
    By default, only allocates ports >= 1024 to avoid conflicts with
    system services (SSH, HTTP, HTTPS, databases, etc.).
    """

    def __init__(self, start_port: int = 10000, end_port: int = 65000):
        # Safety: ensure we don't allocate privileged ports
        if start_port < MIN_SAFE_PORT:
            start_port = MIN_SAFE_PORT
        if end_port > 65535:
            end_port = 65535
        
        self.start_port = start_port
        self.end_port = end_port
        self._allocated: set[int] = set()
        self._lock = Lock()

    def is_port_free(self, port: int) -> bool:
        """Check if a port is available."""
        if port in self._allocated:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('0.0.0.0', port))
                return True
        except OSError:
            return False

    def allocate(self, preferred_port: Optional[int] = None) -> int:
        """
        Allocate a free port.

        If preferred_port is given and available, use it.
        Otherwise, find the next available port.
        
        Note: Ports below MIN_SAFE_PORT (1024) are rejected for safety.
        """
        with self._lock:
            # Try preferred port first (but only if it's in safe range)
            if preferred_port and preferred_port >= MIN_SAFE_PORT and self.is_port_free(preferred_port):
                self._allocated.add(preferred_port)
                return preferred_port

            # Find next available port
            for port in range(self.start_port, self.end_port):
                if self.is_port_free(port):
                    self._allocated.add(port)
                    return port

            raise RuntimeError("No free ports available")

    def release(self, port: int) -> None:
        """Release an allocated port."""
        with self._lock:
            self._allocated.discard(port)

    def release_all(self) -> None:
        """Release all allocated ports."""
        with self._lock:
            self._allocated.clear()


class ServiceRegistry:
    """
    Local service registry for name-based service discovery.

    Services register with their name and get assigned a port.
    Other services can look up endpoints by name.
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        host: str = "127.0.0.1",
    ):
        self.host = host
        self.storage_path = storage_path or Path(".pactown-services.json")
        self._services: dict[str, ServiceEndpoint] = {}
        self._port_allocator = PortAllocator()
        self._lock = Lock()
        self._load()

    def _load(self) -> None:
        """Load service registry from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path) as f:
                    data = json.load(f)
                    for name, info in data.get("services", {}).items():
                        self._services[name] = ServiceEndpoint(
                            name=info["name"],
                            host=info["host"],
                            port=info["port"],
                            health_check=info.get("health_check"),
                        )
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self) -> None:
        """Persist service registry to disk."""
        data = {
            "services": {
                name: {
                    "name": svc.name,
                    "host": svc.host,
                    "port": svc.port,
                    "health_check": svc.health_check,
                }
                for name, svc in self._services.items()
            }
        }
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def register(
        self,
        name: str,
        preferred_port: Optional[int] = None,
        health_check: Optional[str] = None,
    ) -> ServiceEndpoint:
        """
        Register a service and allocate a port.

        If preferred_port is available, use it. Otherwise, allocate dynamically.
        """
        with self._lock:
            # Check if already registered
            if name in self._services:
                existing = self._services[name]
                # Check if existing port is still free
                if self._port_allocator.is_port_free(existing.port):
                    return existing
                # Port is taken, need to reallocate
                self._port_allocator.release(existing.port)

            # Allocate port
            port = self._port_allocator.allocate(preferred_port)

            endpoint = ServiceEndpoint(
                name=name,
                host=self.host,
                port=port,
                health_check=health_check,
            )

            self._services[name] = endpoint
            self._save()

            return endpoint

    def unregister(self, name: str) -> None:
        """Unregister a service."""
        with self._lock:
            if name in self._services:
                self._port_allocator.release(self._services[name].port)
                del self._services[name]
                self._save()

    def get(self, name: str) -> Optional[ServiceEndpoint]:
        """Get service endpoint by name."""
        return self._services.get(name)

    def get_url(self, name: str) -> Optional[str]:
        """Get service URL by name."""
        svc = self.get(name)
        return svc.url if svc else None

    def list_services(self) -> list[ServiceEndpoint]:
        """List all registered services."""
        return list(self._services.values())

    def get_environment(self, service_name: str, dependencies: list[str]) -> dict[str, str]:
        """
        Get environment variables for a service.

        Injects URLs for all dependencies as environment variables.
        """
        env = {}

        # Add own endpoint info
        if service_name in self._services:
            svc = self._services[service_name]
            env["MARKPACT_PORT"] = str(svc.port)
            env["SERVICE_NAME"] = service_name
            env["SERVICE_URL"] = svc.url

        # Add dependency URLs
        for dep_name in dependencies:
            if dep_name in self._services:
                dep = self._services[dep_name]
                # Multiple environment variable formats for flexibility
                env_key = dep_name.upper().replace("-", "_").replace(".", "_")
                env[f"{env_key}_URL"] = dep.url
                env[f"{env_key}_HOST"] = dep.host
                env[f"{env_key}_PORT"] = str(dep.port)

        return env

    def clear(self) -> None:
        """Clear all registrations."""
        with self._lock:
            self._services.clear()
            self._port_allocator.release_all()
            if self.storage_path.exists():
                self.storage_path.unlink()


def find_free_port(start: int = 10000, end: int = 65000) -> int:
    """Find a single free port.
    
    Note: start will be clamped to MIN_SAFE_PORT (1024) minimum for safety.
    """
    # Safety: ensure start is at least MIN_SAFE_PORT
    if start < MIN_SAFE_PORT:
        start = MIN_SAFE_PORT
    allocator = PortAllocator(start, end)
    return allocator.allocate()


def check_port(port: int) -> bool:
    """Check if a specific port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', port))
            return True
    except OSError:
        return False
