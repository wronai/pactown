"""Tests for pactown network module."""

import tempfile
from pathlib import Path

from pactown.network import (
    PortAllocator,
    ServiceEndpoint,
    ServiceRegistry,
    check_port,
    find_free_port,
)


def test_port_allocator_allocate():
    allocator = PortAllocator(start_port=50000, end_port=51000)
    port = allocator.allocate()
    assert 50000 <= port < 51000


def test_port_allocator_preferred_port():
    allocator = PortAllocator()
    # Find a free port first
    free_port = find_free_port(start=50000)

    # Allocate with preferred
    allocated = allocator.allocate(preferred_port=free_port)
    assert allocated == free_port


def test_port_allocator_release():
    allocator = PortAllocator(start_port=50000, end_port=50010)

    # Allocate all ports
    ports = [allocator.allocate() for _ in range(10)]
    assert len(ports) == 10

    # Release one
    allocator.release(ports[0])

    # Should be able to allocate it again
    new_port = allocator.allocate()
    assert new_port == ports[0]


def test_service_endpoint():
    endpoint = ServiceEndpoint(
        name="api",
        host="127.0.0.1",
        port=8001,
        health_check="/health",
    )

    assert endpoint.url == "http://127.0.0.1:8001"
    assert endpoint.health_url == "http://127.0.0.1:8001/health"


def test_service_registry_register():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        endpoint = registry.register("api", preferred_port=50001, health_check="/health")

        assert endpoint.name == "api"
        assert endpoint.port == 50001
        assert endpoint.health_check == "/health"


def test_service_registry_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        registry.register("api", preferred_port=50001)

        endpoint = registry.get("api")
        assert endpoint is not None
        assert endpoint.name == "api"

        assert registry.get("nonexistent") is None


def test_service_registry_get_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        registry.register("api", preferred_port=50001)

        url = registry.get_url("api")
        assert url == "http://127.0.0.1:50001"


def test_service_registry_environment():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        registry.register("database", preferred_port=50001)
        registry.register("api", preferred_port=50002)

        env = registry.get_environment("api", ["database"])

        assert env["DATABASE_URL"] == "http://127.0.0.1:50001"
        assert env["DATABASE_HOST"] == "127.0.0.1"
        assert env["DATABASE_PORT"] == "50001"
        assert env["MARKPACT_PORT"] == "50002"


def test_service_registry_unregister():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        registry.register("api", preferred_port=50001)
        assert registry.get("api") is not None

        registry.unregister("api")
        assert registry.get("api") is None


def test_service_registry_dynamic_port():
    """Test that registry allocates a new port if preferred is busy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        # Register first service
        endpoint1 = registry.register("svc1", preferred_port=50001)

        # Register second service with same preferred port
        # It should get a different port
        endpoint2 = registry.register("svc2", preferred_port=50001)

        assert endpoint1.port != endpoint2.port


def test_find_free_port():
    port = find_free_port()
    assert 10000 <= port < 65000
    assert check_port(port)  # Port should be free


def test_check_port():
    # Find a free port
    port = find_free_port()
    assert check_port(port) is True
