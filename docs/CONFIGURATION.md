# Configuration Reference

[← Back to README](../README.md) | [Specification](SPECIFICATION.md) | [Network](NETWORK.md) | [Deployment →](DEPLOYMENT.md)

---

> **Related:** [Generator](GENERATOR.md) | [Fast Start](FAST_START.md) | [Security Policy](SECURITY_POLICY.md)

Complete reference for `saas.pactown.yaml` configuration files.

## Basic Structure

```yaml
# Ecosystem metadata
name: my-platform
version: 0.1.0
description: My service ecosystem

# Port and sandbox settings
base_port: 8000
sandbox_root: ./.pactown-sandboxes

# Optional registry configuration
registry:
  url: http://localhost:8800
  namespace: default

# Service definitions
services:
  service-name:
    readme: path/to/README.md
    port: 8001
    health_check: /health
    timeout: 30
    env:
      LOG_LEVEL: debug
    depends_on:
      - name: other-service
```

## Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | ✓ | - | Ecosystem name |
| `version` | string | | `0.1.0` | Semantic version |
| `description` | string | | - | Human-readable description |
| `base_port` | int | | `8000` | Starting port for auto-assignment |
| `sandbox_root` | string | | `./.pactown-sandboxes` | Directory for service sandboxes |
| `registry` | object | | - | Registry configuration |
| `services` | object | ✓ | - | Service definitions |

## Registry Configuration

```yaml
registry:
  url: http://localhost:8800    # Registry server URL
  namespace: production         # Namespace for artifacts
  auth_token: ${REGISTRY_TOKEN} # Optional auth (env var)
```

**Source:** [`config.py:RegistryConfig`](../src/pactown/config.py#L45-L55)

## Service Configuration

```yaml
services:
  api:
    readme: services/api/README.md  # Required: path to markpact README
    port: 8001                      # Optional: preferred port
    health_check: /health           # Optional: health endpoint
    timeout: 30                     # Optional: startup timeout (seconds)
    env:                            # Optional: environment variables
      LOG_LEVEL: debug
      DATABASE_HOST: localhost
    depends_on:                     # Optional: dependencies
      - name: database
        endpoint: http://localhost:8003  # Explicit endpoint
        env_var: DATABASE_URL            # Environment variable name
```

### Service Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `readme` | string | ✓ | - | Path to markpact README.md |
| `port` | int | | auto | Preferred port (dynamic if busy) |
| `health_check` | string | | - | Health check endpoint path |
| `timeout` | int | | `60` | Startup timeout in seconds |
| `env` | object | | `{}` | Extra environment variables |
| `depends_on` | list | | `[]` | Service dependencies |

**Source:** [`config.py:ServiceConfig`](../src/pactown/config.py#L20-L42)

### Dependency Fields

```yaml
depends_on:
  - name: database          # Required: dependency service name
    version: "1.0.0"        # Optional: version constraint
    endpoint: http://...    # Optional: explicit endpoint URL
    env_var: DATABASE_URL   # Optional: env var name for injection
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | ✓ | - | Dependency service name |
| `version` | string | | `*` | Version constraint |
| `endpoint` | string | | auto | Explicit endpoint URL |
| `env_var` | string | | `{NAME}_URL` | Environment variable name |

**Source:** [`config.py:DependencyConfig`](../src/pactown/config.py#L8-L18)

## Environment Variables

### Automatic Injection

For each dependency, pactown injects:

```bash
# If api depends on database:
DATABASE_URL=http://127.0.0.1:10000
DATABASE_HOST=127.0.0.1
DATABASE_PORT=10000
```

### Built-in Variables

| Variable | Description |
|----------|-------------|
| `MARKPACT_PORT` | Service's allocated port |
| `SERVICE_NAME` | Service name (from runtime service registry injection) |
| `SERVICE_URL` | Service's own URL |
| `PACTOWN_SERVICE_NAME` | Service name (from dependency resolver injection) |
| `PACTOWN_ECOSYSTEM` | Ecosystem name |

### Custom Variables

```yaml
services:
  api:
    env:
      LOG_LEVEL: debug
      FEATURE_FLAG: "true"
      API_KEY: ${MY_API_KEY}  # From host environment
```

## Complete Example

```yaml
name: saas-platform
version: 0.2.0
description: Complete SaaS platform with microservices

base_port: 8000
sandbox_root: ./.pactown-sandboxes

registry:
  url: http://localhost:8800
  namespace: saas

services:
  # Database service - no dependencies
  database:
    readme: services/database/README.md
    port: 8003
    health_check: /health
    timeout: 30
    env:
      LOG_LEVEL: info

  # API service - depends on database
  api:
    readme: services/api/README.md
    port: 8001
    health_check: /health
    timeout: 30
    depends_on:
      - name: database
        env_var: DATABASE_URL

  # Web frontend - depends on API
  web:
    readme: services/web/README.md
    port: 8002
    health_check: /health
    timeout: 20
    depends_on:
      - name: api
        env_var: API_URL

  # Gateway - depends on all services
  gateway:
    readme: services/gateway/README.md
    port: 8000
    health_check: /health
    timeout: 30
    depends_on:
      - name: api
        env_var: API_URL
      - name: database
        env_var: DATABASE_URL
      - name: web
        env_var: WEB_URL
```

## Validation

Validate configuration before running:

```bash
pactown validate saas.pactown.yaml
```

Checks:
- YAML syntax
- Required fields present
- README files exist
- No circular dependencies
- Dependency services exist

## Loading in Python

```python
from pactown.config import load_config, EcosystemConfig

# From file
config = load_config("saas.pactown.yaml")

# From dict
config = EcosystemConfig.from_dict({
    "name": "test",
    "services": {
        "api": {"readme": "api/README.md", "port": 8001}
    }
})

# Access services
for name, service in config.services.items():
    print(f"{name}: {service.port}")
```

## Schema

JSON Schema for validation: [`schema/pactown.schema.json`](../schema/pactown.schema.json)

```bash
# Validate with external tool
jsonschema -i saas.pactown.yaml schema/pactown.schema.json
```
