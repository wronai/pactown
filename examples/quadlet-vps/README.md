# Quadlet VPS Deployment Example

Deploy Markdown services on a Hetzner VPS using Podman Quadlet.

## Prerequisites

- Hetzner CX53 VPS (or similar) with Ubuntu 22.04+
- Podman 4.4+
- Domain pointing to VPS IP

## Setup

### 1. Install Podman

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y podman

# Verify version (must be 4.4+)
podman version
```

### 2. Enable User Lingering

```bash
# Allow user services to run after logout
loginctl enable-linger $USER
```

### 3. Initialize Pactown Quadlet

```bash
# Install pactown
pip install pactown

# Initialize with your domain
pactown quadlet init \
    --domain yourdomain.com \
    --email admin@yourdomain.com
```

### 4. Start Traefik

```bash
systemctl --user daemon-reload
systemctl --user enable --now traefik.service

# Verify it's running
systemctl --user status traefik.service
```

## Deploy Your First Markdown Service

### Option A: CLI Deploy

```bash
# Create a markdown file
cat > my-docs.md << 'EOF'
# My Documentation

Welcome to my documentation site!

## Features

- Fast and lightweight
- Automatic HTTPS
- Zero maintenance

## API Reference

See our [API docs](/api) for details.
EOF

# Deploy it
pactown quadlet deploy my-docs.md \
    --domain yourdomain.com \
    --subdomain docs \
    --tenant myproject \
    --tls

# Access at: https://docs.yourdomain.com
```

### Option B: Interactive Shell

```bash
pactown quadlet shell --domain yourdomain.com --tenant myproject

# In the shell:
pactown-quadlet> config subdomain api
pactown-quadlet> deploy ./api-docs.md
pactown-quadlet> list
pactown-quadlet> logs api-docs
```

### Option C: REST API

```bash
# Start API server
pactown quadlet api --port 8800 --domain yourdomain.com &

# Deploy via API
curl -X POST http://localhost:8800/deploy/markdown \
  -H "Content-Type: application/json" \
  -d '{
    "markdown_content": "# Hello World\n\nDeployed via API!",
    "subdomain": "hello",
    "domain": "yourdomain.com",
    "tenant_id": "myproject",
    "tls_enabled": true
  }'
```

## Multi-Tenant Setup

Deploy services for multiple tenants:

```bash
# Tenant 1
pactown quadlet deploy ./docs/tenant1.md \
    --domain yourdomain.com \
    --subdomain tenant1 \
    --tenant tenant1

# Tenant 2  
pactown quadlet deploy ./docs/tenant2.md \
    --domain yourdomain.com \
    --subdomain tenant2 \
    --tenant tenant2

# List all services
pactown quadlet list --tenant tenant1
pactown quadlet list --tenant tenant2
```

## Directory Structure

After deployment:

```
~/.config/containers/systemd/
├── traefik.container           # Reverse proxy
├── traefik-letsencrypt.volume  # TLS certificates
├── tenant-myproject/
│   ├── docs.container
│   └── content/
│       └── docs.md
├── tenant-tenant1/
│   └── ...
└── tenant-tenant2/
    └── ...
```

## Management Commands

```bash
# List services
pactown quadlet list --tenant myproject

# View logs
pactown quadlet logs docs --tenant myproject --lines 100

# Restart service
systemctl --user restart docs.service

# Stop service
systemctl --user stop docs.service

# Remove service
systemctl --user disable --now docs.service
rm ~/.config/containers/systemd/tenant-myproject/docs.container
systemctl --user daemon-reload
```

## Resource Limits

Default limits (configurable):
- **CPU**: 0.5 cores
- **Memory**: 256MB (max 512MB)

Modify in the `.container` file:

```ini
PodmanArgs=--cpus=1.0 --memory=512M --memory-reservation=1G
```

## Monitoring

```bash
# Service status
systemctl --user status docs.service

# Real-time logs
journalctl --user -u docs.service -f

# Container stats
podman stats

# All Quadlet services
systemctl --user list-units 'tenant-*'
```

## Backup

```bash
# Backup all Quadlet configs
tar -czf quadlet-backup.tar.gz ~/.config/containers/systemd/

# Backup Let's Encrypt certs
podman volume export traefik-letsencrypt > letsencrypt-backup.tar
```

## Scaling

For 50+ tenants, consider migrating to Kubernetes:

```bash
# Export to Kubernetes YAML
podman generate kube myproject-docs > k8s-docs.yaml

# Use with K3s
kubectl apply -f k8s-docs.yaml
```

## Troubleshooting

### Service won't start

```bash
# Check detailed status
systemctl --user status docs.service -l

# Check container logs
podman logs myproject-docs

# Verify Quadlet generation
/usr/libexec/podman/quadlet --dryrun --user
```

### TLS certificate issues

```bash
# Check Traefik logs
journalctl --user -u traefik.service -f

# Verify DNS is pointing to VPS
dig +short docs.yourdomain.com
```

### Port conflicts

```bash
# Check what's using port 80/443
ss -tlnp | grep -E ':(80|443)'
```
