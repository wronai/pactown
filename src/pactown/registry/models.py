"""Data models for pactown registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class ArtifactVersion:
    """A specific version of an artifact."""
    version: str
    readme_content: str
    checksum: str
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "readme_content": self.readme_content,
            "checksum": self.checksum,
            "published_at": self.published_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArtifactVersion":
        return cls(
            version=data["version"],
            readme_content=data["readme_content"],
            checksum=data["checksum"],
            published_at=datetime.fromisoformat(data["published_at"]),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Artifact:
    """An artifact in the registry (a markpact module)."""
    name: str
    namespace: str = "default"
    description: str = ""
    versions: dict[str, ArtifactVersion] = field(default_factory=dict)
    latest_version: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.namespace}/{self.name}"

    def add_version(self, version: ArtifactVersion) -> None:
        self.versions[version.version] = version
        self.latest_version = version.version
        self.updated_at = datetime.now(timezone.utc)

    def get_version(self, version: str = "latest") -> Optional[ArtifactVersion]:
        if version == "latest" or version == "*":
            version = self.latest_version
        return self.versions.get(version)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "description": self.description,
            "versions": {k: v.to_dict() for k, v in self.versions.items()},
            "latest_version": self.latest_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        versions = {
            k: ArtifactVersion.from_dict(v)
            for k, v in data.get("versions", {}).items()
        }
        return cls(
            name=data["name"],
            namespace=data.get("namespace", "default"),
            description=data.get("description", ""),
            versions=versions,
            latest_version=data.get("latest_version"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            tags=data.get("tags", []),
        )


class RegistryStorage:
    """File-based storage for registry artifacts."""

    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._index_path = self.storage_path / "index.json"
        self._artifacts: dict[str, Artifact] = {}
        self._load()

    def _load(self) -> None:
        if self._index_path.exists():
            with open(self._index_path) as f:
                data = json.load(f)
                for full_name, artifact_data in data.get("artifacts", {}).items():
                    self._artifacts[full_name] = Artifact.from_dict(artifact_data)

    def _save(self) -> None:
        data = {
            "artifacts": {k: v.to_dict() for k, v in self._artifacts.items()},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._index_path, "w") as f:
            json.dump(data, f, indent=2)

    def get(self, namespace: str, name: str) -> Optional[Artifact]:
        return self._artifacts.get(f"{namespace}/{name}")

    def list(self, namespace: Optional[str] = None) -> list[Artifact]:
        if namespace:
            return [a for a in self._artifacts.values() if a.namespace == namespace]
        return list(self._artifacts.values())

    def save_artifact(self, artifact: Artifact) -> None:
        self._artifacts[artifact.full_name] = artifact
        self._save()

    def delete(self, namespace: str, name: str) -> bool:
        key = f"{namespace}/{name}"
        if key in self._artifacts:
            del self._artifacts[key]
            self._save()
            return True
        return False

    def search(self, query: str) -> list[Artifact]:
        query = query.lower()
        results = []
        for artifact in self._artifacts.values():
            if (query in artifact.name.lower() or
                query in artifact.description.lower() or
                any(query in tag.lower() for tag in artifact.tags)):
                results.append(artifact)
        return results
