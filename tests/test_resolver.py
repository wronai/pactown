"""Tests for dependency resolver."""

import pytest

from pactown.config import DependencyConfig, EcosystemConfig, ServiceConfig
from pactown.resolver import DependencyResolver


def make_config(services: dict) -> EcosystemConfig:
    """Helper to create test config."""
    svc_configs = {}
    for name, data in services.items():
        deps = [DependencyConfig.from_dict(d) for d in data.get("depends_on", [])]
        svc_configs[name] = ServiceConfig(
            name=name,
            readme=f"{name}/README.md",
            port=data.get("port", 8000),
            depends_on=deps,
        )
    return EcosystemConfig(name="test", services=svc_configs)


def test_startup_order_no_deps():
    config = make_config({
        "a": {},
        "b": {},
        "c": {},
    })
    resolver = DependencyResolver(config)
    order = resolver.get_startup_order()
    assert len(order) == 3


def test_startup_order_linear():
    config = make_config({
        "database": {},
        "api": {"depends_on": [{"name": "database"}]},
        "web": {"depends_on": [{"name": "api"}]},
    })
    resolver = DependencyResolver(config)
    order = resolver.get_startup_order()

    assert order.index("database") < order.index("api")
    assert order.index("api") < order.index("web")


def test_startup_order_diamond():
    config = make_config({
        "database": {},
        "cache": {},
        "api": {"depends_on": [{"name": "database"}, {"name": "cache"}]},
        "web": {"depends_on": [{"name": "api"}]},
    })
    resolver = DependencyResolver(config)
    order = resolver.get_startup_order()

    assert order.index("database") < order.index("api")
    assert order.index("cache") < order.index("api")
    assert order.index("api") < order.index("web")


def test_circular_dependency_detection():
    config = make_config({
        "a": {"depends_on": [{"name": "b"}]},
        "b": {"depends_on": [{"name": "c"}]},
        "c": {"depends_on": [{"name": "a"}]},
    })
    resolver = DependencyResolver(config)

    with pytest.raises(ValueError, match="Circular dependency"):
        resolver.get_startup_order()


def test_shutdown_order():
    config = make_config({
        "database": {},
        "api": {"depends_on": [{"name": "database"}]},
    })
    resolver = DependencyResolver(config)

    startup = resolver.get_startup_order()
    shutdown = resolver.get_shutdown_order()

    assert shutdown == list(reversed(startup))


def test_resolve_service_deps():
    config = make_config({
        "database": {"port": 8003},
        "api": {
            "port": 8001,
            "depends_on": [{"name": "database"}],
        },
    })
    resolver = DependencyResolver(config)

    deps = resolver.resolve_service_deps("api")
    assert len(deps) == 1
    assert deps[0].name == "database"
    assert deps[0].endpoint == "http://localhost:8003"


def test_get_environment():
    config = make_config({
        "database": {"port": 8003},
        "api": {
            "port": 8001,
            "depends_on": [{"name": "database", "env_var": "DB_URL"}],
        },
    })
    # Manually set env_var on the dependency
    config.services["api"].depends_on[0].env_var = "DB_URL"

    resolver = DependencyResolver(config)
    env = resolver.get_environment("api")

    assert env["DB_URL"] == "http://localhost:8003"
    assert env["PACTOWN_SERVICE_NAME"] == "api"
    assert env["MARKPACT_PORT"] == "8001"


def test_validate_missing_dep():
    config = make_config({
        "api": {"depends_on": [{"name": "missing-service"}]},
    })
    resolver = DependencyResolver(config)

    issues = resolver.validate()
    assert len(issues) > 0
    assert "missing-service" in issues[0]


def test_print_graph():
    config = make_config({
        "database": {},
        "api": {"depends_on": [{"name": "database"}]},
    })
    resolver = DependencyResolver(config)

    graph = resolver.print_graph()
    assert "database" in graph
    assert "api" in graph
