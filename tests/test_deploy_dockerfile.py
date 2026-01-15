"""Tests for Dockerfile generation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from pactown.deploy.base import DeploymentConfig
from pactown.deploy.docker import DockerBackend


def test_python_dockerfile_healthcheck_does_not_use_curl() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    with TemporaryDirectory() as tmp:
        sandbox_path = Path(tmp)
        (sandbox_path / "requirements.txt").write_text("fastapi\n")

        dockerfile = backend._create_dockerfile(sandbox_path, base_image="python:3.12-slim")

    assert "curl" not in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "python -c" in dockerfile
    assert "MARKPACT_PORT" in dockerfile


def test_node_dockerfile_falls_back_when_package_lock_missing() -> None:
    backend = DockerBackend(DeploymentConfig.for_development())

    with TemporaryDirectory() as tmp:
        sandbox_path = Path(tmp)
        (sandbox_path / "package.json").write_text('{"name":"test","version":"1.0.0"}\n')

        dockerfile = backend._create_dockerfile(sandbox_path, base_image="python:3.12-slim")

    assert "curl" not in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm install" in dockerfile
    assert "package-lock.json" in dockerfile
    assert "node -e" in dockerfile
    assert "MARKPACT_PORT" in dockerfile
