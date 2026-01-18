from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SubdomainSeparator = Literal["-", "."]


def coerce_subdomain_separator(value: Optional[str]) -> SubdomainSeparator:
    return "." if value == "." else "-"


def normalize_host(value: str) -> str:
    v = (value or "").strip().lower()
    if v.startswith("http://"):
        v = v[len("http://") :]
    elif v.startswith("https://"):
        v = v[len("https://") :]
    v = v.split("/", 1)[0]
    v = v.split(":", 1)[0]
    v = v.strip(".")
    return v


def normalize_domain(value: str) -> str:
    v = normalize_host(value)
    if v.startswith("www."):
        v = v[len("www.") :]
    return v


def is_local_domain(domain: str) -> bool:
    d = normalize_domain(domain)
    return d in {"localhost", "127.0.0.1", "0.0.0.0"}


def build_origin(*, scheme: Literal["http", "https"], host: str, port: Optional[int] = None) -> str:
    h = normalize_host(host)
    if port is None:
        return f"{scheme}://{h}"
    return f"{scheme}://{h}:{int(port)}"


def web_base_url(domain: str, web_host_port: int) -> str:
    if is_local_domain(domain):
        return build_origin(scheme="http", host="localhost", port=int(web_host_port))
    return build_origin(scheme="https", host=normalize_domain(domain))


def api_base_url(domain: str, api_host_port: int) -> str:
    if is_local_domain(domain):
        return build_origin(scheme="http", host="localhost", port=int(api_host_port))
    return build_origin(scheme="https", host=f"api.{normalize_domain(domain)}")


def to_dns_label(value: str, *, max_len: int = 63, fallback: str = "x") -> str:
    v = (value or "").lower().strip()
    v = re.sub(r"[^a-z0-9]+", "-", v)
    v = re.sub(r"-+", "-", v).strip("-")
    if not v:
        v = fallback
    return v[:max_len]


class DomainConfig(BaseModel):
    domain: str = Field(default="localhost")
    subdomain_separator: SubdomainSeparator = Field(default="-")

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v: str) -> str:
        out = normalize_domain(v)
        if not out:
            return "localhost"
        return out

    @field_validator("subdomain_separator")
    @classmethod
    def _normalize_separator(cls, v: str) -> SubdomainSeparator:
        return coerce_subdomain_separator(v)


class ProjectHostParts(BaseModel):
    project_id: int
    username: str


_PROJECT_SUBDOMAIN_RE = re.compile(r"^(?P<project_id>\d+)(?:-|\.)(?P<username>[a-z0-9-]+)$")


def parse_project_subdomain(subdomain: str) -> Optional[ProjectHostParts]:
    s = (subdomain or "").strip().lower()
    m = _PROJECT_SUBDOMAIN_RE.match(s)
    if not m:
        return None
    try:
        project_id = int(m.group("project_id"))
    except Exception:
        return None
    username = m.group("username")
    if not username:
        return None
    return ProjectHostParts(project_id=project_id, username=username)


def build_project_subdomain(project_id: int, username: str, *, separator: SubdomainSeparator) -> str:
    pid = int(project_id)
    sep = coerce_subdomain_separator(separator)

    prefix = f"{pid}{sep}"
    max_username_len = max(1, 63 - len(prefix))
    uname = to_dns_label(username, max_len=max_username_len, fallback="user")

    return f"{pid}{sep}{uname}"


def build_project_host(project_id: int, username: str, *, domain: str, separator: SubdomainSeparator) -> str:
    base_domain = normalize_domain(domain)
    sub = build_project_subdomain(project_id, username, separator=separator)
    return f"{sub}.{base_domain}"


def parse_project_host(host: str, *, domain: str) -> Optional[ProjectHostParts]:
    h = normalize_host(host)
    base_domain = normalize_domain(domain)
    suffix = f".{base_domain}" if base_domain else ""

    if not suffix or not h.endswith(suffix):
        return None

    subdomain = h[: -len(suffix)]
    return parse_project_subdomain(subdomain)


def build_service_subdomain(service_name: str, username: str, *, separator: SubdomainSeparator) -> str:
    sep = coerce_subdomain_separator(separator)
    service_label = to_dns_label(service_name, max_len=20, fallback="app")
    tenant_label = to_dns_label(username, max_len=30, fallback="user")

    if sep == ".":
        return f"{service_label}.{tenant_label}".strip(".")

    label = f"{service_label}-{tenant_label}".strip("-")
    return label[:63].strip("-")
