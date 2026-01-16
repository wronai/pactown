# Production Deployment Guide

[← Back to README](../README.md) | [Configuration](CONFIGURATION.md) | [Quadlet →](QUADLET.md)

---

> **Related:** [Network](NETWORK.md) | [Security](SECURITY.md) | [User Isolation](USER_ISOLATION.md)

This guide covers deploying pactown ecosystems to production using Docker, Podman, and Kubernetes.

## Deployment Backends

| Backend | Use Case | Security |
|---------|----------|----------|
| **Local** | Development | Basic |
| **Docker** | Single server | Good |
| **Podman** | Rootless containers | Excellent |
| **Quadlet** | VPS production (systemd-native) | Excellent |
| **Kubernetes** | Orchestrated cluster | Enterprise |
| **Compose** | Multi-container | Good |

## Quick Start

### Generate Deployment Files

```bash
# Docker Compose (development)
pactown deploy saas.pactown.yaml -o ./deploy

# Docker Compose (production)
pactown deploy saas.pactown.yaml -o ./deploy --production

# Kubernetes manifests
pactown deploy saas.pactown.yaml -o ./deploy --kubernetes --production
```

### Run with Docker Compose

```bash
cd deploy
docker compose up -d

# Or with Podman
podman-compose up -d
```

### Deploy to Kubernetes

```bash
kubectl apply -f deploy/kubernetes/
```

## Docker Compose

### Generated Files

| File | Purpose |
|------|---------|
| `docker-compose.yaml` | Main service definitions |
| `docker-compose.override.yaml` | Development overrides |
| `docker-compose.prod.yaml` | Production settings |

### Development Mode

```bash
docker compose up -d
docker compose logs -f
```

### Production Mode

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

### Production Features

- Resource limits (CPU, memory)
- Health checks with retries
- Restart policies
- Security options (no-new-privileges, read-only fs)
- Capability dropping

## Podman (Rootless)

Podman provides **rootless containers** - no root daemon required.

### Why Podman for Production?

- **No daemon** - no single point of failure
- **Rootless** - runs as regular user
- **SELinux integration** - enhanced security
- **Systemd integration** - native service management
- **OCI-compliant** - compatible with Docker images

### Usage

```python
from pactown.deploy import PodmanBackend, DeploymentConfig

config = DeploymentConfig.for_production()
podman = PodmanBackend(config)

# Build and deploy
podman.build_image("api", dockerfile_path, context_path)
podman.deploy("api", "pactown/api:latest", port=8001, env={...})
```

### Systemd Integration

Generate systemd unit files for production:

```python
unit = podman.generate_systemd_unit("api")
# Write to /etc/systemd/system/pactown-api.service
```

```bash
systemctl enable pactown-api
systemctl start pactown-api
```

### Podman Pods

Group related containers in a pod (like Kubernetes):

```python
podman.create_pod("my-app", services=["api", "worker"], ports=[8001, 8002])
```

## Kubernetes

### Generated Manifests

For each service, pactown generates:

- **Namespace** - isolated environment
- **Deployment** - with rolling updates
- **Service** - internal DNS
- **ConfigMap** - environment variables
- **NetworkPolicy** - security rules

### Security Features

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
```

### Autoscaling

Generate HorizontalPodAutoscaler:

```python
from pactown.deploy import KubernetesBackend

k8s = KubernetesBackend(config)
hpa = k8s.generate_hpa("api", min_replicas=2, max_replicas=10, target_cpu=70)
```

### Network Policies

Services can only communicate within the pactown namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
spec:
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              managed-by: pactown
```

## Security Configuration

### DeploymentConfig Options

```python
from pactown.deploy import DeploymentConfig, DeploymentMode

config = DeploymentConfig(
    mode=DeploymentMode.PRODUCTION,
    
    # Container security
    rootless=True,              # Podman rootless mode
    read_only_fs=True,          # Read-only filesystem
    no_new_privileges=True,     # Prevent privilege escalation
    drop_capabilities=["ALL"],  # Drop all Linux capabilities
    
    # Resource limits
    memory_limit="512m",
    cpu_limit="0.5",
    
    # Health checks
    health_check_interval="10s",
    health_check_retries=5,
)
```

### Production Preset

```python
config = DeploymentConfig.for_production()
```

This enables:
- Rootless containers
- Read-only filesystem
- No new privileges
- All capabilities dropped
- Stricter resource limits
- More frequent health checks

## Container Images

### Dockerfile Generation

Pactown auto-generates secure Dockerfiles:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Security: run as non-root user
RUN useradd -m -u 1000 appuser

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "main.py"]
```

### Build and Push

```python
from pactown.deploy import DockerBackend

docker = DockerBackend(config)

# Build
result = docker.build_image("api", dockerfile_path, context_path, tag="v1.0.0")

# Push to registry
docker.push_image("pactown/api:v1.0.0", registry="ghcr.io/myorg")
```

## Service Discovery

### Docker Compose

Services communicate via container names:

```yaml
environment:
  DATABASE_URL: http://database:8003
  API_URL: http://api:8001
```

### Kubernetes

Services use internal DNS:

```
http://api.pactown.svc.cluster.local:8001
```

## Monitoring

### Health Checks

All backends support health checks:

```python
result = backend.deploy(
    service_name="api",
    image_name="pactown/api:latest",
    port=8001,
    env={},
    health_check="/health",  # Health endpoint
)
```

### Logs

```python
logs = backend.logs("api", tail=100)
```

### Status

```python
status = backend.status("api")
# {
#   "running": True,
#   "health": "healthy",
#   "container_id": "abc123",
# }
```

## CLI Reference

```bash
# Generate Docker Compose
pactown deploy CONFIG [-o OUTPUT] [--production]

# Generate Kubernetes
pactown deploy CONFIG [-o OUTPUT] --kubernetes [--production]

# Options
-o, --output      Output directory (default: .)
-p, --production  Production configuration
-k, --kubernetes  Generate Kubernetes manifests
```

## Source Code Reference

| Module | Description |
|--------|-------------|
| [`deploy/base.py`](../src/pactown/deploy/base.py) | Base classes and config |
| [`deploy/docker.py`](../src/pactown/deploy/docker.py) | Docker backend |
| [`deploy/podman.py`](../src/pactown/deploy/podman.py) | Podman backend |
| [`deploy/kubernetes.py`](../src/pactown/deploy/kubernetes.py) | Kubernetes backend |
| [`deploy/compose.py`](../src/pactown/deploy/compose.py) | Compose generator |

## Best Practices

1. **Use rootless containers** (Podman) when possible
2. **Enable read-only filesystem** for production
3. **Drop all capabilities** and add only what's needed
4. **Set resource limits** to prevent resource exhaustion
5. **Use health checks** for automatic recovery
6. **Enable network policies** in Kubernetes
7. **Run as non-root user** inside containers
8. **Use secrets management** for sensitive data
9. **Enable logging and monitoring**
10. **Use rolling updates** for zero-downtime deployments
