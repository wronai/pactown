# Network & Service Discovery

[← Back to README](../README.md) | [Configuration](CONFIGURATION.md) | [Deployment →](DEPLOYMENT.md)

---

> **Related:** [Specification](SPECIFICATION.md) | [Generator](GENERATOR.md)

This document describes pactown's dynamic port allocation and service discovery system.

## Problem

When running multiple services:
- **Port conflicts** – services may try to use the same port
- **Hardcoded URLs** – services reference each other by fixed ports
- **Manual coordination** – developers must track which ports are in use

## Solution

Pactown uses **dynamic port allocation** and **name-based service discovery**:

```yaml
services:
  api:
    depends_on:
      - name: database  # ← resolved to actual URL at runtime
```

Services communicate via **names**, not ports. The actual port is injected via environment variables.

## How It Works

### 1. Port Allocation

When starting a service, pactown:

1. Tries the configured `port` first
2. If busy, finds the next free port (starting from 10000)
3. Logs: `Port 8003 busy, using 10042`

**Source:** [`network.py:PortAllocator`](../src/pactown/network.py#L33-L74)

```python
class PortAllocator:
    def allocate(self, preferred_port: Optional[int] = None) -> int:
        # Try preferred port first
        if preferred_port and self.is_port_free(preferred_port):
            return preferred_port
        # Find next available
        for port in range(self.start_port, self.end_port):
            if self.is_port_free(port):
                return port
```

### 2. Service Registry

The `ServiceRegistry` tracks running services and their endpoints:

**Source:** [`network.py:ServiceRegistry`](../src/pactown/network.py#L77-L215)

```python
registry = ServiceRegistry()

# Register service with dynamic port
endpoint = registry.register("api", preferred_port=8001)
print(endpoint.url)  # http://127.0.0.1:10001 (if 8001 was busy)

# Get dependency URLs
env = registry.get_environment("web", ["api", "database"])
# {
#   "API_URL": "http://127.0.0.1:10001",
#   "API_HOST": "127.0.0.1",
#   "API_PORT": "10001",
#   "DATABASE_URL": "http://127.0.0.1:10002",
#   ...
# }
```

### 3. Environment Injection

Each service receives environment variables for its dependencies:

| Variable | Example | Description |
|----------|---------|-------------|
| `{SERVICE}_URL` | `DATABASE_URL=http://127.0.0.1:10002` | Full URL |
| `{SERVICE}_HOST` | `DATABASE_HOST=127.0.0.1` | Host only |
| `{SERVICE}_PORT` | `DATABASE_PORT=10002` | Port only |
| `MARKPACT_PORT` | `MARKPACT_PORT=10001` | Own port |
| `SERVICE_NAME` | `SERVICE_NAME=api` | Service name |

## Configuration

### Enable/Disable Dynamic Ports

Dynamic ports are **enabled by default**. To use fixed ports only:

```python
orchestrator = Orchestrator(config, dynamic_ports=False)
```

Or via API:

```python
from pactown import Orchestrator

orch = Orchestrator.from_file("saas.pactown.yaml", dynamic_ports=True)
```

### Port Range

Default range: **10000-65000**

Customize in code:

```python
from pactown.network import PortAllocator

allocator = PortAllocator(start_port=20000, end_port=30000)
```

## Persistence

The service registry persists to `.pactown-sandboxes/.pactown-services.json`:

```json
{
  "services": {
    "database": {
      "name": "database",
      "host": "127.0.0.1",
      "port": 10000,
      "health_check": "/health"
    },
    "api": {
      "name": "api",
      "host": "127.0.0.1",
      "port": 10001,
      "health_check": "/health"
    }
  }
}
```

This allows services to find each other even after restarts.

## API Reference

### `ServiceEndpoint`

```python
@dataclass
class ServiceEndpoint:
    name: str           # Service name
    host: str           # Host address
    port: int           # Allocated port
    health_check: str   # Health endpoint
    
    @property
    def url(self) -> str: ...        # http://host:port
    @property
    def health_url(self) -> str: ... # http://host:port/health
```

### `ServiceRegistry`

```python
class ServiceRegistry:
    def register(name, preferred_port, health_check) -> ServiceEndpoint
    def unregister(name) -> None
    def get(name) -> Optional[ServiceEndpoint]
    def get_url(name) -> Optional[str]
    def list_services() -> list[ServiceEndpoint]
    def get_environment(service_name, dependencies) -> dict[str, str]
    def clear() -> None
```

### `PortAllocator`

```python
class PortAllocator:
    def is_port_free(port) -> bool
    def allocate(preferred_port=None) -> int
    def release(port) -> None
    def release_all() -> None
```

## Utility Functions

```python
from pactown.network import find_free_port, check_port

# Find any free port
port = find_free_port()

# Check if specific port is available
if check_port(8080):
    print("Port 8080 is free")
```

## Future: Docker Network Mode

For full network isolation with DNS-style hostnames:

```yaml
# Future feature
network:
  mode: docker
  name: pactown-net
```

Services would be accessible as `database.pactown.local`, `api.pactown.local`, etc.
