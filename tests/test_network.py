"""Tests for pactown network module."""

import tempfile
from pathlib import Path

import pytest

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
    block_start = None
    for candidate in range(45000, 60000, 11):
        probe = PortAllocator(candidate, candidate + 10)
        if all(probe.is_port_free(candidate + i) for i in range(10)):
            block_start = candidate
            break
    if block_start is None:
        pytest.skip("Could not find 10 consecutive free ports")

    allocator = PortAllocator(start_port=block_start, end_port=block_start + 10)

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
        preferred = find_free_port(start=45000, end=60000)

        endpoint = registry.register("api", preferred_port=preferred, health_check="/health")

        assert endpoint.name == "api"
        assert endpoint.port == preferred
        assert endpoint.health_check == "/health"


def test_service_registry_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")
        preferred = find_free_port(start=45000, end=60000)

        registry.register("api", preferred_port=preferred)

        endpoint = registry.get("api")
        assert endpoint is not None
        assert endpoint.name == "api"

        assert registry.get("nonexistent") is None


def test_service_registry_get_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")
        preferred = find_free_port(start=45000, end=60000)

        registry.register("api", preferred_port=preferred)

        url = registry.get_url("api")
        assert url == f"http://127.0.0.1:{preferred}"


def test_service_registry_environment():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")

        db_port = find_free_port(start=45000, end=60000)
        api_port = find_free_port(start=db_port + 1, end=60000)

        registry.register("database", preferred_port=db_port)
        registry.register("api", preferred_port=api_port)

        env = registry.get_environment("api", ["database"])

        assert env["DATABASE_URL"] == f"http://127.0.0.1:{db_port}"
        assert env["DATABASE_HOST"] == "127.0.0.1"
        assert env["DATABASE_PORT"] == str(db_port)
        assert env["MARKPACT_PORT"] == str(api_port)


def test_service_registry_unregister():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")
        preferred = find_free_port(start=45000, end=60000)

        registry.register("api", preferred_port=preferred)
        assert registry.get("api") is not None

        registry.unregister("api")
        assert registry.get("api") is None


def test_service_registry_dynamic_port():
    """Test that registry allocates a new port if preferred is busy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ServiceRegistry(storage_path=Path(tmpdir) / "services.json")
        preferred = find_free_port(start=45000, end=60000)

        # Register first service
        endpoint1 = registry.register("svc1", preferred_port=preferred)

        # Register second service with same preferred port
        # It should get a different port
        endpoint2 = registry.register("svc2", preferred_port=preferred)

        assert endpoint1.port != endpoint2.port


def test_find_free_port():
    port = find_free_port()
    assert 10000 <= port < 65000
    assert check_port(port)  # Port should be free


def test_check_port():
    # Find a free port
    port = find_free_port()
    assert check_port(port) is True
