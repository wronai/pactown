"""FastAPI endpoints for Quadlet deployment management.

Provides a REST API for generating and deploying Markdown services
using Podman Quadlet on VPS infrastructure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .base import DeploymentConfig
from .quadlet import (
    QuadletBackend,
    QuadletConfig,
    QuadletTemplates,
    generate_markdown_service_quadlet,
    generate_traefik_quadlet,
)


# Pydantic models for API
class DeploymentRequest(BaseModel):
    """Request to deploy a Markdown service."""

    markdown_content: str = Field(..., description="Markdown content to deploy")
    name: Optional[str] = Field(None, description="Service name (auto-generated from content if not provided)")
    tenant_id: str = Field("default", description="Tenant identifier")
    subdomain: Optional[str] = Field(None, description="Subdomain for the service")
    domain: str = Field("localhost", description="Base domain")
    tls_enabled: bool = Field(False, description="Enable TLS/HTTPS")

    # Resource limits
    cpus: str = Field("0.5", description="CPU limit")
    memory: str = Field("256M", description="Memory limit")

    # Image
    image: str = Field(
        "ghcr.io/pactown/markdown-server:latest",
        description="Container image for Markdown server"
    )


class ContainerRequest(BaseModel):
    """Request to generate a container Quadlet file."""

    name: str = Field(..., description="Container name")
    image: str = Field(..., description="Container image")
    port: int = Field(..., description="Container port")
    tenant_id: str = Field("default", description="Tenant identifier")
    subdomain: Optional[str] = Field(None, description="Subdomain")
    domain: str = Field("localhost", description="Base domain")
    tls_enabled: bool = Field(False, description="Enable TLS")

    # Environment variables
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")

    # Volumes
    volumes: list[str] = Field(default_factory=list, description="Volume mounts")

    # Health check
    health_check: Optional[str] = Field(None, description="Health check endpoint")

    # Resource limits
    cpus: str = Field("0.5", description="CPU limit")
    memory: str = Field("256M", description="Memory limit")


class TraefikRequest(BaseModel):
    """Request to generate Traefik Quadlet files."""

    domain: str = Field(..., description="Base domain for Traefik")
    email: Optional[str] = Field(None, description="Email for Let's Encrypt")


class DeploymentResponse(BaseModel):
    """Response from deployment operation."""

    success: bool
    service_name: str
    message: str
    url: Optional[str] = None
    unit_files: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class QuadletFileResponse(BaseModel):
    """Response containing generated Quadlet files."""

    files: list[dict[str, str]]  # [{filename: content}]
    tenant_path: str
    instructions: str


class ServiceStatus(BaseModel):
    """Service status information."""

    name: str
    running: bool
    state: str
    pid: Optional[str] = None
    tenant: str
    url: Optional[str] = None


class ListServicesResponse(BaseModel):
    """Response listing all services."""

    tenant_id: str
    services: list[ServiceStatus]
    total: int


# Create FastAPI app
def create_quadlet_api(
    default_domain: str = "localhost",
    default_tenant: str = "default",
    user_mode: bool = True,
) -> FastAPI:
    """Create FastAPI application for Quadlet management."""

    app = FastAPI(
        title="Pactown Quadlet API",
        description="Deploy Markdown services on VPS using Podman Quadlet",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Dependency to get backend
    def get_backend(
        tenant_id: str = default_tenant,
        domain: str = default_domain,
    ) -> QuadletBackend:
        quadlet_config = QuadletConfig(
            tenant_id=tenant_id,
            domain=domain,
            user_mode=user_mode,
        )
        deploy_config = DeploymentConfig.for_production()
        return QuadletBackend(deploy_config, quadlet_config)

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy", "service": "quadlet-api"}

    @app.get("/version")
    async def version():
        """Get Podman/Quadlet version."""
        backend = get_backend()
        podman_version = backend.get_quadlet_version()
        return {
            "api_version": "1.0.0",
            "podman_version": podman_version,
            "quadlet_available": backend.is_available(),
        }

    @app.post("/generate/markdown", response_model=QuadletFileResponse)
    async def generate_markdown_quadlet(request: DeploymentRequest):
        """Generate Quadlet files for a Markdown service.

        This endpoint generates Quadlet unit files that can be used
        to deploy a Markdown file as a web service.
        """
        # Create config
        quadlet_config = QuadletConfig(
            tenant_id=request.tenant_id,
            domain=request.domain,
            subdomain=request.subdomain,
            tls_enabled=request.tls_enabled,
            cpus=request.cpus,
            memory=request.memory,
        )

        # Generate service name from content if not provided
        name = request.name
        if not name:
            # Generate name from first heading or hash
            lines = request.markdown_content.strip().split("\n")
            for line in lines:
                if line.startswith("# "):
                    name = line[2:].strip().lower().replace(" ", "-").replace("_", "-")[:32]
                    break
            if not name:
                name = f"md-{hashlib.sha256(request.markdown_content.encode()).hexdigest()[:8]}"

        # Create temporary markdown file
        content_hash = hashlib.sha256(request.markdown_content.encode()).hexdigest()[:12]
        markdown_path = Path(f"/tmp/pactown-markdown-{content_hash}.md")
        markdown_path.write_text(request.markdown_content)

        # Generate units
        units = generate_markdown_service_quadlet(
            markdown_path=markdown_path,
            config=quadlet_config,
            image=request.image,
        )

        files = []
        for unit in units:
            files.append({
                "filename": unit.filename,
                "content": unit.content,
            })

        return QuadletFileResponse(
            files=files,
            tenant_path=str(quadlet_config.tenant_path),
            instructions=f"""
To deploy this service:

1. Save the unit file(s) to: {quadlet_config.tenant_path}/
2. Run: systemctl --user daemon-reload
3. Run: systemctl --user enable --now {name}.service
4. Access at: {"https" if request.tls_enabled else "http"}://{quadlet_config.full_domain}

Or use the /deploy/markdown endpoint to deploy automatically.
""".strip(),
        )

    @app.post("/generate/container", response_model=QuadletFileResponse)
    async def generate_container_quadlet(request: ContainerRequest):
        """Generate Quadlet files for a custom container."""
        quadlet_config = QuadletConfig(
            tenant_id=request.tenant_id,
            domain=request.domain,
            subdomain=request.subdomain,
            tls_enabled=request.tls_enabled,
            cpus=request.cpus,
            memory=request.memory,
        )

        unit = QuadletTemplates.container(
            name=request.name,
            image=request.image,
            port=request.port,
            config=quadlet_config,
            env=request.env,
            health_check=request.health_check,
            volumes=request.volumes,
        )

        return QuadletFileResponse(
            files=[{
                "filename": unit.filename,
                "content": unit.content,
            }],
            tenant_path=str(quadlet_config.tenant_path),
            instructions=f"""
To deploy this container:

1. Save the unit file to: {quadlet_config.tenant_path}/{unit.filename}
2. Run: systemctl --user daemon-reload
3. Run: systemctl --user enable --now {request.name}.service
4. Access at: {"https" if request.tls_enabled else "http"}://{quadlet_config.full_domain}
""".strip(),
        )

    @app.post("/generate/traefik", response_model=QuadletFileResponse)
    async def generate_traefik_files(request: TraefikRequest):
        """Generate Traefik reverse proxy Quadlet files."""
        quadlet_config = QuadletConfig(
            domain=request.domain,
        )

        units = generate_traefik_quadlet(quadlet_config)

        files = []
        for unit in units:
            content = unit.content
            if request.email:
                content = content.replace(
                    f"admin@{request.domain}",
                    request.email
                )
            files.append({
                "filename": unit.filename,
                "content": content,
            })

        return QuadletFileResponse(
            files=files,
            tenant_path=str(quadlet_config.systemd_path),
            instructions=f"""
To deploy Traefik:

1. Save the unit files to: {quadlet_config.systemd_path}/
2. Run: systemctl --user daemon-reload
3. Run: systemctl --user enable --now traefik.service

Traefik will automatically:
- Handle HTTP to HTTPS redirect
- Provision Let's Encrypt certificates
- Route traffic to your services based on Host labels
""".strip(),
        )

    @app.post("/deploy/markdown", response_model=DeploymentResponse)
    async def deploy_markdown(request: DeploymentRequest, background_tasks: BackgroundTasks):
        """Deploy a Markdown file as a web service.

        This endpoint generates Quadlet files and starts the service.
        """
        quadlet_config = QuadletConfig(
            tenant_id=request.tenant_id,
            domain=request.domain,
            subdomain=request.subdomain,
            tls_enabled=request.tls_enabled,
            cpus=request.cpus,
            memory=request.memory,
            user_mode=user_mode,
        )

        deploy_config = DeploymentConfig.for_production()
        backend = QuadletBackend(deploy_config, quadlet_config)

        if not backend.is_available():
            raise HTTPException(
                status_code=503,
                detail="Podman with Quadlet support not available"
            )

        # Generate name
        name = request.name
        if not name:
            lines = request.markdown_content.strip().split("\n")
            for line in lines:
                if line.startswith("# "):
                    name = line[2:].strip().lower().replace(" ", "-").replace("_", "-")[:32]
                    break
            if not name:
                name = f"md-{hashlib.sha256(request.markdown_content.encode()).hexdigest()[:8]}"

        # Save markdown content
        content_dir = quadlet_config.tenant_path / "content"
        content_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = content_dir / f"{name}.md"
        markdown_path.write_text(request.markdown_content)

        # Generate and save units
        units = generate_markdown_service_quadlet(
            markdown_path=markdown_path,
            config=quadlet_config,
            image=request.image,
        )

        unit_files = []
        for unit in units:
            path = unit.save(quadlet_config.tenant_path)
            unit_files.append(str(path))

        # Reload and start
        backend._systemctl("daemon-reload")
        backend._systemctl("enable", f"{name}.service")
        result = backend._systemctl("start", f"{name}.service")

        url = f"{'https' if request.tls_enabled else 'http'}://{quadlet_config.full_domain}"

        if result.returncode == 0:
            return DeploymentResponse(
                success=True,
                service_name=name,
                message=f"Successfully deployed {name}",
                url=url,
                unit_files=unit_files,
            )
        else:
            return DeploymentResponse(
                success=False,
                service_name=name,
                message="Deployment failed",
                error=result.stderr,
                unit_files=unit_files,
            )

    @app.delete("/deploy/{service_name}", response_model=DeploymentResponse)
    async def undeploy_service(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Remove a deployed service."""
        backend = get_backend(tenant_id=tenant_id)
        result = backend.stop(service_name)

        return DeploymentResponse(
            success=result.success,
            service_name=service_name,
            message="Service removed" if result.success else "Failed to remove service",
            error=result.error,
        )

    @app.get("/services", response_model=ListServicesResponse)
    async def list_services(tenant_id: str = default_tenant):
        """List all services for a tenant."""
        backend = get_backend(tenant_id=tenant_id)
        services = backend.list_services()

        service_statuses = []
        for svc in services:
            status = svc["status"]
            service_statuses.append(ServiceStatus(
                name=svc["name"],
                running=status.get("running", False),
                state=status.get("state", "unknown"),
                pid=status.get("pid"),
                tenant=tenant_id,
            ))

        return ListServicesResponse(
            tenant_id=tenant_id,
            services=service_statuses,
            total=len(service_statuses),
        )

    @app.get("/services/{service_name}", response_model=ServiceStatus)
    async def get_service_status(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Get status of a specific service."""
        backend = get_backend(tenant_id=tenant_id)
        status = backend.status(service_name)

        return ServiceStatus(
            name=service_name,
            running=status.get("running", False),
            state=status.get("state", "unknown"),
            pid=status.get("pid"),
            tenant=tenant_id,
        )

    @app.post("/services/{service_name}/start")
    async def start_service(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Start a service."""
        backend = get_backend(tenant_id=tenant_id)
        backend._systemctl("daemon-reload")
        result = backend._systemctl("start", f"{service_name}.service")

        if result.returncode == 0:
            return {"success": True, "message": f"Started {service_name}"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr)

    @app.post("/services/{service_name}/stop")
    async def stop_service(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Stop a service."""
        backend = get_backend(tenant_id=tenant_id)
        result = backend._systemctl("stop", f"{service_name}.service")

        if result.returncode == 0:
            return {"success": True, "message": f"Stopped {service_name}"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr)

    @app.post("/services/{service_name}/restart")
    async def restart_service(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Restart a service."""
        backend = get_backend(tenant_id=tenant_id)
        result = backend._systemctl("restart", f"{service_name}.service")

        if result.returncode == 0:
            return {"success": True, "message": f"Restarted {service_name}"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr)

    @app.get("/services/{service_name}/logs", response_class=PlainTextResponse)
    async def get_service_logs(
        service_name: str,
        tenant_id: str = default_tenant,
        lines: int = 100,
    ):
        """Get logs for a service."""
        backend = get_backend(tenant_id=tenant_id)
        logs = backend.logs(service_name, tail=lines)
        return logs

    @app.get("/unit/{service_name}", response_class=PlainTextResponse)
    async def get_unit_file(
        service_name: str,
        tenant_id: str = default_tenant,
    ):
        """Get the Quadlet unit file content for a service."""
        quadlet_config = QuadletConfig(tenant_id=tenant_id, user_mode=user_mode)

        for ext in ["container", "pod", "network", "volume", "kube"]:
            unit_path = quadlet_config.tenant_path / f"{service_name}.{ext}"
            if unit_path.exists():
                return unit_path.read_text()

        raise HTTPException(status_code=404, detail="Unit file not found")

    return app


# Default app instance
app = create_quadlet_api()


def run_api(
    host: str = "0.0.0.0",
    port: int = 8800,
    domain: str = "localhost",
    tenant: str = "default",
):
    """Run the Quadlet API server."""
    import uvicorn

    global app
    app = create_quadlet_api(
        default_domain=domain,
        default_tenant=tenant,
    )

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_api()
