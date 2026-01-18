"""FastAPI server for pactown registry."""

import hashlib
from pathlib import Path
from typing import Optional

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .models import Artifact, ArtifactVersion, RegistryStorage


class PublishRequest(BaseModel):
    name: str
    version: str
    readme_content: str
    namespace: str = "default"
    description: str = ""
    tags: list[str] = []
    metadata: dict = {}


class PublishResponse(BaseModel):
    success: bool
    artifact: str
    version: str
    checksum: str


class ArtifactInfo(BaseModel):
    name: str
    namespace: str
    description: str
    latest_version: Optional[str]
    versions: list[str]
    tags: list[str]


class VersionInfo(BaseModel):
    version: str
    readme_content: str
    checksum: str
    published_at: str
    metadata: dict


def create_app(storage_path: str = "./.pactown-registry") -> FastAPI:
    """Create the registry FastAPI application."""

    app = FastAPI(
        title="Pactown Registry",
        description="Local artifact registry for markpact modules",
        version="0.1.0",
    )

    # CORS configuration - configurable via environment
    # Default allows all origins for local development registry
    cors_origins = os.environ.get("PACTOWN_REGISTRY_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,  # nosec: configurable, default * for local dev
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    storage = RegistryStorage(Path(storage_path))

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "pactown-registry"}

    @app.get("/v1/artifacts", response_model=list[ArtifactInfo])
    def list_artifacts(
        namespace: Optional[str] = Query(None, description="Filter by namespace"),
        search: Optional[str] = Query(None, description="Search query"),
    ):
        if search:
            artifacts = storage.search(search)
        else:
            artifacts = storage.list(namespace)

        return [
            ArtifactInfo(
                name=a.name,
                namespace=a.namespace,
                description=a.description,
                latest_version=a.latest_version,
                versions=list(a.versions.keys()),
                tags=a.tags,
            )
            for a in artifacts
        ]

    @app.get("/v1/artifacts/{namespace}/{name}", response_model=ArtifactInfo)
    def get_artifact(namespace: str, name: str):
        artifact = storage.get(namespace, name)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return ArtifactInfo(
            name=artifact.name,
            namespace=artifact.namespace,
            description=artifact.description,
            latest_version=artifact.latest_version,
            versions=list(artifact.versions.keys()),
            tags=artifact.tags,
        )

    @app.get("/v1/artifacts/{namespace}/{name}/{version}", response_model=VersionInfo)
    def get_version(namespace: str, name: str, version: str):
        artifact = storage.get(namespace, name)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        ver = artifact.get_version(version)
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")

        return VersionInfo(
            version=ver.version,
            readme_content=ver.readme_content,
            checksum=ver.checksum,
            published_at=ver.published_at.isoformat(),
            metadata=ver.metadata,
        )

    @app.get("/v1/artifacts/{namespace}/{name}/{version}/readme")
    def get_readme(namespace: str, name: str, version: str):
        artifact = storage.get(namespace, name)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        ver = artifact.get_version(version)
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")

        return {"content": ver.readme_content}

    @app.post("/v1/publish", response_model=PublishResponse)
    def publish(req: PublishRequest):
        checksum = hashlib.sha256(req.readme_content.encode()).hexdigest()

        artifact = storage.get(req.namespace, req.name)
        if not artifact:
            artifact = Artifact(
                name=req.name,
                namespace=req.namespace,
                description=req.description,
                tags=req.tags,
            )

        version = ArtifactVersion(
            version=req.version,
            readme_content=req.readme_content,
            checksum=checksum,
            metadata=req.metadata,
        )

        artifact.add_version(version)
        if req.description:
            artifact.description = req.description
        if req.tags:
            artifact.tags = list(set(artifact.tags + req.tags))

        storage.save_artifact(artifact)

        return PublishResponse(
            success=True,
            artifact=artifact.full_name,
            version=req.version,
            checksum=checksum,
        )

    @app.delete("/v1/artifacts/{namespace}/{name}")
    def delete_artifact(namespace: str, name: str):
        if storage.delete(namespace, name):
            return {"success": True, "message": f"Deleted {namespace}/{name}"}
        raise HTTPException(status_code=404, detail="Artifact not found")

    @app.get("/v1/namespaces")
    def list_namespaces():
        namespaces = set(a.namespace for a in storage.list())
        return {"namespaces": sorted(namespaces)}

    return app


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8800, help="Port to bind to")
@click.option("--storage", default="./.pactown-registry", help="Storage path")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def main(host: str, port: int, storage: str, reload: bool):
    """Start the pactown registry server."""
    create_app(storage)
    uvicorn.run(
        "pactown.registry.server:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


if __name__ == "__main__":
    main()
