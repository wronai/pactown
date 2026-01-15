"""Tests for pactown registry."""

import tempfile
from pathlib import Path

from pactown.registry.models import Artifact, ArtifactVersion, RegistryStorage


def test_artifact_version_to_dict():
    version = ArtifactVersion(
        version="1.0.0",
        readme_content="# Test",
        checksum="abc123",
    )
    data = version.to_dict()
    assert data["version"] == "1.0.0"
    assert data["readme_content"] == "# Test"
    assert data["checksum"] == "abc123"


def test_artifact_version_from_dict():
    data = {
        "version": "2.0.0",
        "readme_content": "# Content",
        "checksum": "def456",
        "published_at": "2024-01-01T00:00:00",
        "metadata": {"key": "value"},
    }
    version = ArtifactVersion.from_dict(data)
    assert version.version == "2.0.0"
    assert version.metadata == {"key": "value"}


def test_artifact_full_name():
    artifact = Artifact(name="my-service", namespace="prod")
    assert artifact.full_name == "prod/my-service"


def test_artifact_add_version():
    artifact = Artifact(name="test", namespace="default")
    version = ArtifactVersion(
        version="1.0.0",
        readme_content="# Test",
        checksum="abc",
    )
    artifact.add_version(version)

    assert artifact.latest_version == "1.0.0"
    assert "1.0.0" in artifact.versions


def test_artifact_get_version():
    artifact = Artifact(name="test", namespace="default")
    v1 = ArtifactVersion(version="1.0.0", readme_content="v1", checksum="a")
    v2 = ArtifactVersion(version="2.0.0", readme_content="v2", checksum="b")

    artifact.add_version(v1)
    artifact.add_version(v2)

    assert artifact.get_version("1.0.0").readme_content == "v1"
    assert artifact.get_version("latest").readme_content == "v2"
    assert artifact.get_version("*").readme_content == "v2"
    assert artifact.get_version("3.0.0") is None


def test_registry_storage_save_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = RegistryStorage(Path(tmpdir))

        artifact = Artifact(name="test-svc", namespace="default")
        artifact.add_version(ArtifactVersion(
            version="1.0.0",
            readme_content="# Hello",
            checksum="abc",
        ))

        storage.save_artifact(artifact)

        # Retrieve
        retrieved = storage.get("default", "test-svc")
        assert retrieved is not None
        assert retrieved.name == "test-svc"
        assert retrieved.latest_version == "1.0.0"


def test_registry_storage_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = RegistryStorage(Path(tmpdir))

        for ns in ["default", "prod"]:
            artifact = Artifact(name=f"svc-{ns}", namespace=ns)
            storage.save_artifact(artifact)

        all_artifacts = storage.list()
        assert len(all_artifacts) == 2

        default_only = storage.list(namespace="default")
        assert len(default_only) == 1
        assert default_only[0].namespace == "default"


def test_registry_storage_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = RegistryStorage(Path(tmpdir))

        artifact = Artifact(name="to-delete", namespace="default")
        storage.save_artifact(artifact)

        assert storage.get("default", "to-delete") is not None

        result = storage.delete("default", "to-delete")
        assert result is True
        assert storage.get("default", "to-delete") is None


def test_registry_storage_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = RegistryStorage(Path(tmpdir))

        a1 = Artifact(name="user-api", namespace="default", description="User management")
        a2 = Artifact(name="order-api", namespace="default", description="Order processing")
        a3 = Artifact(name="payment", namespace="default", tags=["api", "stripe"])

        storage.save_artifact(a1)
        storage.save_artifact(a2)
        storage.save_artifact(a3)

        results = storage.search("api")
        assert len(results) == 3  # matches name or tag

        results = storage.search("user")
        assert len(results) == 1
        assert results[0].name == "user-api"


def test_registry_storage_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        # First instance
        storage1 = RegistryStorage(Path(tmpdir))
        artifact = Artifact(name="persistent", namespace="default")
        artifact.add_version(ArtifactVersion(
            version="1.0.0",
            readme_content="# Persist",
            checksum="xyz",
        ))
        storage1.save_artifact(artifact)

        # Second instance (simulating restart)
        storage2 = RegistryStorage(Path(tmpdir))
        retrieved = storage2.get("default", "persistent")

        assert retrieved is not None
        assert retrieved.latest_version == "1.0.0"
