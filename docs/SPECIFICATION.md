# Pactown System Specification

[← Back to README](../README.md) | [Configuration →](CONFIGURATION.md)

---

## Problem Statement

Modern software systems are increasingly composed of multiple independent services that need to work together. However, setting up and managing these systems presents several challenges:

1. **Configuration Complexity** – Each service has its own dependencies, ports, and configuration
2. **Dependency Management** – Services depend on each other and must start in correct order
3. **Environment Isolation** – Services should run in isolated environments to avoid conflicts
4. **Cross-Language Integration** – Teams use different languages but need to integrate seamlessly
5. **Documentation Drift** – Documentation becomes outdated as code changes
6. **Onboarding Friction** – New developers struggle to set up complex multi-service environments

## Solution: Pactown

Pactown addresses these challenges by:

1. **Executable Documentation** – Using markpact, each service's README.md is the source of truth
2. **Declarative Configuration** – YAML-based ecosystem configuration for all services
3. **Automatic Orchestration** – Services start in dependency order with health checks
4. **Sandbox Isolation** – Each service runs in its own virtual environment
5. **Local Registry** – Share and version markpact artifacts across projects
6. **Language Agnostic** – Mix Python, Node.js, Go, Rust, PHP in one ecosystem

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Pactown Ecosystem                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  saas.pactown.yaml                                                   │
│       │                                                              │
│       ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                      Orchestrator                             │   │
│  │  • Reads configuration                                        │   │
│  │  • Resolves dependencies                                      │   │
│  │  • Manages lifecycle                                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│       │                                                              │
│       ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  Dependency Resolver                          │   │
│  │  • Topological sort                                           │   │
│  │  • Circular detection                                         │   │
│  │  • Environment injection                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│       │                                                              │
│       ▼                                                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Sandbox Manager                             │   │
│  │  • Creates isolated sandboxes                                 │   │
│  │  • Manages processes                                          │   │
│  │  • Handles cleanup                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│       │                                                              │
│       ▼                                                              │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐        │
│  │Service1│  │Service2│  │Service3│  │Service4│  │Service5│        │
│  │ :8001  │  │ :8002  │  │ :8003  │  │ :8004  │  │ :8005  │        │
│  │markpact│  │markpact│  │markpact│  │markpact│  │markpact│        │
│  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Pactown Registry                                │
├─────────────────────────────────────────────────────────────────────┤
│  • Stores markpact artifacts                                        │
│  • Version management                                                │
│  • Namespace isolation                                               │
│  • REST API for publish/pull                                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Ecosystem Configuration (saas.pactown.yaml)

The central configuration file that defines:
- Ecosystem metadata (name, version)
- Service definitions
- Dependencies between services
- Registry settings

### 2. Orchestrator

Manages the complete lifecycle:
- Validates configuration
- Coordinates service startup/shutdown
- Monitors health
- Handles failures

### 3. Dependency Resolver

Ensures correct startup order:
- Builds dependency graph
- Detects circular dependencies
- Calculates topological order
- Injects environment variables

### 4. Sandbox Manager

Isolates each service:
- Creates virtual environments
- Manages processes
- Handles port allocation
- Cleans up on shutdown

### 5. Registry

Shares artifacts across projects:
- Stores README content
- Tracks versions
- Provides REST API
- Supports namespaces

## Service Communication

Services communicate via:

1. **Environment Variables** – Dependency endpoints injected as env vars
2. **HTTP/REST** – Standard HTTP APIs
3. **Health Checks** – Configurable endpoints for monitoring

Example:
```yaml
services:
  api:
    port: 8001
    health_check: /health
    
  web:
    port: 8002
    depends_on:
      - name: api
        env_var: API_URL  # Injected as API_URL=http://localhost:8001
```

## Use Cases

### 1. SaaS Platform Development

Build complete platforms with:
- Web frontend (React/Vue)
- REST API (FastAPI/Express)
- Database service
- Background workers
- Admin CLI

### 2. Microservices Architecture

Deploy polyglot microservices:
- Python ML service
- Go API gateway
- Node.js real-time service
- Rust performance service

### 3. Development Environments

Standardize team environments:
- Consistent setup across machines
- Documentation always up-to-date
- One command to start everything

### 4. Rapid Prototyping

Quick experimentation:
- Mix and match services
- Pull pre-built components from registry
- Iterate quickly

## Benefits

| Traditional | Pactown |
|-------------|---------|
| Docker Compose + separate docs | Single source of truth |
| Manual dependency management | Automatic resolution |
| Complex setup scripts | `pactown up` |
| Documentation gets stale | Docs = code |
| Per-language tooling | Unified orchestration |

## Limitations

- Services must be compatible with markpact format
- Local development focus (production deployment is separate)
- Single-machine orchestration (not distributed)

## Future Directions

1. **Docker Integration** – Generate docker-compose from ecosystem
2. **Kubernetes Support** – Export to K8s manifests
3. **Remote Registry** – Cloud-hosted artifact registry
4. **Service Mesh** – Automatic service discovery
5. **Hot Reload** – Watch mode for development
