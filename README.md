# Pactown 🏘️

**Decentralized Service Ecosystem Orchestrator** – Build interconnected microservices from Markdown using [markpact](https://github.com/wronai/markpact).

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

## Overview

Pactown enables you to compose multiple independent markpact projects into a unified, decentralized service ecosystem. Each service is defined in its own `README.md`, runs in its own sandbox, and communicates with other services through well-defined interfaces.

```
┌─────────────────────────────────────────────────────────────────┐
│                     Pactown Ecosystem                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │   Web    │───▶│   API    │───▶│ Database │    │   CLI    │  │
│  │ :8002    │    │  :8001   │    │  :8003   │    │  shell   │  │
│  │ React    │    │ FastAPI  │    │ Postgres │    │  Python  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │               │               │         │
│       ▼               ▼               ▼               ▼         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              markpact sandboxes (isolated)                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

- **🔗 Service Composition** – Combine multiple markpact READMEs into one ecosystem
- **📦 Local Registry** – Store and share markpact artifacts across projects
- **🔄 Dependency Resolution** – Automatic startup order based on service dependencies
- **🏥 Health Checks** – Monitor service health with configurable endpoints
- **🌐 Multi-Language** – Mix Python, Node.js, Go, Rust in one ecosystem
- **🔒 Isolated Sandboxes** – Each service runs in its own environment

## Installation

```bash
pip install pactown
```

Or install from source:

```bash
git clone https://github.com/wronai/pactown
cd pactown
make install
```

## Quick Start

### 1. Create ecosystem configuration

```yaml
# saas.pactown.yaml
name: my-saas
version: 0.1.0

services:
  api:
    readme: services/api/README.md
    port: 8001
    health_check: /health

  web:
    readme: services/web/README.md
    port: 8002
    depends_on:
      - name: api
        endpoint: http://localhost:8001
```

### 2. Create service READMEs

Each service is a standard markpact README:

```markdown
# API Service

REST API for the application.

---

\`\`\`markpact:deps python
fastapi
uvicorn
\`\`\`

\`\`\`markpact:file python path=main.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
\`\`\`

\`\`\`markpact:run python
uvicorn main:app --port ${MARKPACT_PORT:-8001}
\`\`\`
```

### 3. Start the ecosystem

```bash
pactown up saas.pactown.yaml
```

## Commands

| Command | Description |
|---------|-------------|
| `pactown up <config>` | Start all services |
| `pactown down <config>` | Stop all services |
| `pactown status <config>` | Show service status |
| `pactown validate <config>` | Validate configuration |
| `pactown graph <config>` | Show dependency graph |
| `pactown init` | Initialize new ecosystem |
| `pactown publish <config>` | Publish to registry |
| `pactown pull <config>` | Pull dependencies |

## Registry

Pactown includes a local registry for sharing markpact artifacts:

```bash
# Start registry
pactown-registry --port 8800

# Publish artifact
pactown publish saas.pactown.yaml --registry http://localhost:8800

# Pull dependencies
pactown pull saas.pactown.yaml --registry http://localhost:8800
```

### Registry API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/artifacts` | GET | List artifacts |
| `/v1/artifacts/{ns}/{name}` | GET | Get artifact info |
| `/v1/artifacts/{ns}/{name}/{version}/readme` | GET | Get README content |
| `/v1/publish` | POST | Publish artifact |

## Configuration Reference

```yaml
name: ecosystem-name        # Required: ecosystem name
version: 0.1.0              # Semantic version
description: ""             # Optional description
base_port: 8000             # Starting port for auto-assignment
sandbox_root: ./.pactown-sandboxes  # Sandbox directory

registry:
  url: http://localhost:8800
  namespace: default

services:
  service-name:
    readme: path/to/README.md   # Path to markpact README
    port: 8001                  # Service port
    health_check: /health       # Health check endpoint
    timeout: 60                 # Startup timeout (seconds)
    replicas: 1                 # Number of instances
    auto_restart: true          # Restart on failure
    env:                        # Environment variables
      KEY: value
    depends_on:                 # Dependencies
      - name: other-service
        endpoint: http://localhost:8000
        env_var: OTHER_SERVICE_URL
```

## Examples

See the `examples/` directory for complete ecosystem examples:

- **SaaS Platform** – Web + API + Database + CLI
- **Microservices** – Multiple language services
- **Event-Driven** – Services with message queues

## Architecture

```
pactown/
├── src/pactown/
│   ├── __init__.py          # Package exports
│   ├── cli.py               # CLI commands
│   ├── config.py            # Configuration models
│   ├── orchestrator.py      # Service orchestration
│   ├── resolver.py          # Dependency resolution
│   ├── sandbox_manager.py   # Sandbox management
│   └── registry/
│       ├── __init__.py
│       ├── server.py        # Registry API server
│       ├── client.py        # Registry client
│       └── models.py        # Data models
├── examples/
│   ├── saas-platform/       # Complete SaaS example
│   └── microservices/       # Microservices example
├── tests/
├── Makefile
├── pyproject.toml
└── README.md
```

## License

Apache License 2.0 – see [LICENSE](LICENSE) for details.
