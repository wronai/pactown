# SaaS Platform Example

Complete SaaS platform demonstrating pactown's ability to orchestrate multiple interconnected services.

## Architecture

```text
                    ┌─────────────┐
                    │   Gateway   │ :8000
                    │  (FastAPI)  │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │     Web     │ │     API     │ │  Database   │
    │   :8002     │ │   :8001     │ │   :8003     │
    │   (HTML)    │ │  (FastAPI)  │ │  (SQLite)   │
    └─────────────┘ └──────┬──────┘ └─────────────┘
                           │               ▲
                           └───────────────┘
                                   │
                           ┌───────┴───────┐
                           │      CLI      │
                           │   (Click)     │
                           └───────────────┘
```

## Services

| Service | Port | Technology | Description |
|---------|------|------------|-------------|
| Gateway | 8000 | FastAPI | API gateway, routes requests |
| API | 8001 | FastAPI | REST API for users/stats |
| Web | 8002 | HTML/JS | Web frontend dashboard |
| Database | 8003 | SQLite/FastAPI | Key-value database service |
| CLI | - | Click/Rich | Admin command-line tool |

## Quick Start

```bash
# Install pactown
pip install pactown

# Start the ecosystem
cd examples/saas-platform
pactown up saas.pactown.yaml

# Or dry-run to see the plan
pactown up saas.pactown.yaml --dry-run
```

## Startup Order

Pactown automatically resolves dependencies and starts services in order:

1. **Database** (no dependencies)
2. **API** (depends on Database)
3. **Web** (depends on API)
4. **CLI** (depends on API, Database)
5. **Gateway** (depends on API, Database, Web)

## Using the Platform

Once running:

- **Web Dashboard**: http://localhost:8002
- **API Docs**: http://localhost:8001/docs
- **Gateway Health**: http://localhost:8000/gateway/health

### CLI Commands

```bash
# In the CLI sandbox
cd .pactown-sandboxes/cli

# List users
python cli.py users list

# Add a user
python cli.py users add "John Doe" "john@example.com"

# Check service health
python cli.py health

# View stats
python cli.py stats
```

## Environment Variables

Each service receives injected environment variables for its dependencies:

| Service | Variable | Value |
|---------|----------|-------|
| API | `DATABASE_URL` | `http://localhost:8003` |
| Web | `API_URL` | `http://localhost:8001` |
| CLI | `API_URL` | `http://localhost:8001` |
| CLI | `DATABASE_URL` | `http://localhost:8003` |
| Gateway | `API_URL` | `http://localhost:8001` |
| Gateway | `DATABASE_URL` | `http://localhost:8003` |
| Gateway | `WEB_URL` | `http://localhost:8002` |

## File Structure

```text
saas-platform/
├── saas.pactown.yaml           # Ecosystem configuration
├── README.md                   # This file
└── services/
    ├── api/
    │   └── README.md           # API service (markpact)
    ├── web/
    │   └── README.md           # Web frontend (markpact)
    ├── database/
    │   └── README.md           # Database service (markpact)
    ├── cli/
    │   └── README.md           # CLI tool (markpact)
    └── gateway/
        └── README.md           # API gateway (markpact)
```

## Customization

### Adding a New Service

1. Create `services/new-service/README.md` with markpact blocks
2. Add to `saas.pactown.yaml`:

```yaml
services:
  new-service:
    readme: services/new-service/README.md
    port: 8004
    health_check: /health
    depends_on:
      - name: api
        endpoint: http://localhost:8001
```

3. Restart the ecosystem: `pactown down saas.pactown.yaml && pactown up saas.pactown.yaml`

### Changing Ports

Update the port in `saas.pactown.yaml` and any dependent services will automatically receive the updated endpoint.

## Troubleshooting

### Port Already in Use

```bash
# Find what's using the port
lsof -i :8001

# Kill the process or change the port in saas.pactown.yaml
```

### Service Won't Start

```bash
# Check the sandbox logs
cat .pactown-sandboxes/api/app.log

# Or run the service manually
cd .pactown-sandboxes/api
source .venv/bin/activate
python -m uvicorn app.main:app --port 8001
```

### Validation Errors

```bash
# Validate configuration
pactown validate saas.pactown.yaml
```
