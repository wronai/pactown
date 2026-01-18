import pytest

from pactown.platform import (
    build_project_host,
    build_project_subdomain,
    build_service_subdomain,
    normalize_domain,
    normalize_host,
    parse_project_host,
)


def test_normalize_host_strips_scheme_and_port():
    assert normalize_host("https://www.Example.com:8443/path") == "www.example.com"


def test_normalize_domain_strips_www_and_scheme():
    assert normalize_domain("https://www.Example.com:8443/path") == "example.com"


def test_build_project_host_dash_separator_normalizes_username():
    assert build_project_host(3, "Jan Kowalski", domain="pactown.com", separator="-") == "3-jan-kowalski.pactown.com"


def test_build_project_host_dot_separator_normalizes_username():
    assert build_project_host(3, "Jan", domain="pactown.com", separator=".") == "3.jan.pactown.com"


@pytest.mark.parametrize(
    "host",
    [
        "3-jan.pactown.com",
        "3.jan.pactown.com",
        "3-JAN.pactown.com",
        "https://3-jan.pactown.com/",
    ],
)
def test_parse_project_host(host: str):
    parts = parse_project_host(host, domain="pactown.com")
    assert parts is not None
    assert parts.project_id == 3
    assert parts.username == "jan"


def test_build_project_subdomain_limits_length():
    sub = build_project_subdomain(999, "a" * 200, separator="-")
    assert len(sub) <= 63
    assert sub.startswith("999-")


def test_build_service_subdomain_dash():
    assert build_service_subdomain("API", "Jan", separator="-") == "api-jan"


def test_build_service_subdomain_dot():
    assert build_service_subdomain("API", "Jan", separator=".") == "api.jan"
