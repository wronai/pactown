# Podman Quadlet Deployment Guide

Deploy Markdown services on any VPS using Podman Quadlet - a lightweight alternative to Kubernetes.

## Overview

Quadlet generates systemd unit files from simple `.container`, `.pod`, `.network` files, providing:

- **Zero daemon overhead** - No kubelet, etcd, or control-plane
- **Native systemd integration** - Auto-restart, logging, dependencies
- **Rootless containers** - Enhanced security by default
- **Simple file-based config** - Files in `~/.config/containers/systemd/`
- **Perfect for MVP** - Ideal for single VPS deployments (e.g., Hetzner CX53)

Related:

- [`docs/SECURITY.md`](SECURITY.md) - hardening + injection test suite
- [`docs/CLOUDFLARE_WORKERS_COMPARISON.md`](CLOUDFLARE_WORKERS_COMPARISON.md) - when Quadlet VPS beats Workers
- [`examples/`](../examples/) - practical deployments

## Quick Start

### 1. Initialize Environment

```bash
# Initialize with Traefik reverse proxy
pactown quadlet init --domain pactown.com --email admin@pactown.com

# This creates:
# ~/.config/containers/systemd/traefik.container
# ~/.config/containers/systemd/traefik-letsencrypt.volume
```

### 2. Deploy a Markdown File

```bash
# Deploy README.md to docs.pactown.com
pactown quadlet deploy ./README.md \
    --domain pactown.com \
    --subdomain docs \
    --tenant user01 \
    --tls

# Access at: https://docs.pactown.com
```

For more practical “copy & customize” services, see:

- `examples/email-llm-responder/README.md`
- `examples/api-gateway-webhooks/README.md`
- `examples/realtime-notifications/README.md`

### 3. Manage Services

```bash
# List services
pactown quadlet list --tenant user01

# View logs
pactown quadlet logs my-service --lines 100

# Interactive shell
pactown quadlet shell --domain pactown.com --tenant user01
```

## CLI Commands

### `pactown quadlet init`

Initialize Quadlet environment with Traefik reverse proxy.

```bash
pactown quadlet init --domain <domain> [--email <email>] [--system]
```

Options:
- `--domain, -d` - Base domain for Traefik (required)
- `--email, -e` - Email for Let's Encrypt certificates
- `--system` - Use system-wide systemd (requires root)

### `pactown quadlet deploy`

Deploy a Markdown file as a web service.

```bash
pactown quadlet deploy <markdown_path> --domain <domain> [options]
```

Options:
- `--domain, -d` - Base domain (required)
- `--subdomain, -s` - Subdomain for the service
- `--tenant, -t` - Tenant ID (default: "default")
- `--tls/--no-tls` - Enable TLS (default: enabled)
- `--image` - Container image for Markdown server

### `pactown quadlet generate`

Generate Quadlet files without deploying.

```bash
pactown quadlet generate <markdown_path> [options]
```

Options:
- `--output, -o` - Output directory (default: current)
- `--domain, -d` - Domain
- `--subdomain, -s` - Subdomain
- `--tenant, -t` - Tenant ID
- `--tls/--no-tls` - Enable TLS labels

### `pactown quadlet shell`

Start interactive deployment shell.

```bash
pactown quadlet shell [--domain <domain>] [--tenant <tenant>]
```

### `pactown quadlet api`

Start REST API server for programmatic deployments.

```bash
pactown quadlet api [--host <host>] [--port <port>] [--domain <domain>]
```

Access API docs at `http://localhost:8800/docs`

### `pactown quadlet list`

List all services for a tenant.

```bash
pactown quadlet list [--tenant <tenant>]
```

### `pactown quadlet logs`

Show logs for a service.

```bash
pactown quadlet logs <service_name> [--tenant <tenant>] [--lines <n>]
```

## Interactive Shell

The interactive shell provides a REPL-style interface:

```bash
pactown quadlet shell --domain pactown.com

pactown-quadlet> status
pactown-quadlet> config tenant user01
pactown-quadlet> deploy ./README.md docs
pactown-quadlet> list
pactown-quadlet> logs my-service
pactown-quadlet> help
```

### Shell Commands

| Command | Description |
|---------|-------------|
| `status` | Show configuration and status |
| `config <setting> <value>` | Configure settings |
| `generate <path>` | Generate Quadlet files |
| `generate_container <name> <image> <port>` | Generate custom container |
| `generate_traefik` | Generate Traefik files |
| `deploy <path> [subdomain]` | Deploy Markdown service |
| `undeploy <name>` | Remove a service |
| `start <name>` | Start a service |
| `stop <name>` | Stop a service |
| `restart <name>` | Restart a service |
| `list` | List all services |
| `logs <name>` | Show service logs |
| `reload` | Reload systemd daemon |
| `init` | Initialize environment |
| `export <dir>` | Export unit files |

## REST API

Start the API server:

```bash
pactown quadlet api --port 8800 --domain pactown.com
```

### Endpoints

#### Generate Markdown Quadlet

```bash
POST /generate/markdown
Content-Type: application/json

{
  "markdown_content": "# My Documentation\n\nContent here...",
  "name": "my-docs",
  "tenant_id": "user01",
  "subdomain": "docs",
  "domain": "pactown.com",
  "tls_enabled": true
}
```

#### Deploy Markdown

```bash
POST /deploy/markdown
Content-Type: application/json

{
  "markdown_content": "# API Documentation\n\n...",
  "subdomain": "api",
  "domain": "pactown.com",
  "tenant_id": "user01",
  "tls_enabled": true
}
```

#### List Services

```bash
GET /services?tenant_id=user01
```

#### Service Management

```bash
POST /services/{name}/start
POST /services/{name}/stop
POST /services/{name}/restart
GET /services/{name}/logs?lines=100
DELETE /deploy/{name}
```

## File Structure

```
~/.config/containers/systemd/
├── traefik.container           # Traefik reverse proxy
├── traefik-letsencrypt.volume  # Let's Encrypt certificates
├── tenant-user01/
│   ├── docs.container          # User's docs service
│   ├── api.container           # User's API service
│   └── content/
│       ├── docs.md             # Markdown content
│       └── api.md
└── tenant-user02/
    └── ...
```

## Quadlet File Examples

### Container Unit (.container)

```ini
[Unit]
Description=Pactown service: docs (tenant: user01)
After=network-online.target

[Container]
ContainerName=user01-docs
Image=ghcr.io/pactown/markdown-server:latest

Environment=MARKDOWN_TITLE=Documentation
Environment=PORT=8080

PublishPort=8080:8080

# Traefik routing
Label=traefik.enable=true
Label=traefik.http.routers.docs.rule=Host(`docs.pactown.com`)
Label=traefik.http.routers.docs.tls=true
Label=traefik.http.routers.docs.tls.certresolver=letsencrypt

# Resource limits
PodmanArgs=--cpus=0.5 --memory=256M

# Security
PodmanArgs=--security-opt=no-new-privileges:true

AutoUpdate=registry

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

### Pod Unit (.pod)

```ini
[Unit]
Description=Pactown pod: app
After=network-online.target

[Pod]
PodName=user01-app
PublishPort=8080:8080
PublishPort=8081:8081
Network=pactown-net

[Install]
WantedBy=default.target
```

### Network Unit (.network)

```ini
[Unit]
Description=Pactown network

[Network]
NetworkName=pactown-net
Driver=bridge
Label=pactown.managed=true

[Install]
WantedBy=default.target
```

## Comparison: Quadlet vs Kubernetes

| Aspect | Podman Quadlet | Kubernetes (K3s) |
|--------|---------------|------------------|
| Config files | 1-5 per user | 5+ per user + globals |
| Networking | Pod networks, Traefik | Ingress + Services |
| Certificates | Traefik Let's Encrypt | cert-manager |
| Resource limits | systemd cgroups | ResourceQuota, HPA |
| Scaling | Single-node | Multi-node, auto-scaling |
| Security | Rootless, user namespaces | RBAC, NetworkPolicies |
| Overhead | Zero daemons | kubelet, etcd, API server |
| Best for | MVP, single VPS | Production, multi-node |

## Migration to Kubernetes

When you outgrow single-node deployment:

```bash
# Convert Quadlet containers to Kubernetes YAML
podman generate kube my-container > k8s-manifests.yaml

# Use with Helm for templating
helm template ./chart --set userId=user01 > user01-deploy.yaml
```

## Requirements

- **Podman 4.4+** - Required for Quadlet support
- **systemd** - For service management
- **Linux** - Tested on Fedora, RHEL, Ubuntu 22.04+

### Check Podman Version

```bash
podman version
# Must be 4.4.0 or higher
```

### Install on Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install podman
```

### Install on Fedora/RHEL

```bash
sudo dnf install podman
```

## Troubleshooting

### Service Won't Start

```bash
# Check systemd status
systemctl --user status my-service.service

# View detailed logs
journalctl --user -u my-service.service -f

# Verify unit file syntax
podman-system-migrate
systemctl --user daemon-reload
```

### Permission Issues

```bash
# Enable lingering for user services
loginctl enable-linger $USER

# Verify user systemd is running
systemctl --user status
```

### Traefik Not Routing

```bash
# Check Traefik logs
journalctl --user -u traefik.service -f

# Verify container labels
podman inspect my-container | grep -A20 Labels
```

## Best Practices

1. **Use tenant isolation** - Separate directories per tenant
2. **Enable TLS** - Always use `--tls` in production
3. **Set resource limits** - Prevent runaway containers
4. **Enable auto-update** - Keep images current
5. **Use rootless mode** - Default, most secure
6. **Monitor with journalctl** - Native logging integration
