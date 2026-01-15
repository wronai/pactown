# Polyglot Microservices Example

Demonstrates pactown's ability to orchestrate services written in different programming languages.

## Architecture

```text
                    ┌─────────────────┐
                    │   Go Gateway    │ :8080
                    │   (net/http)    │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │   Node.js API   │           │   Python ML     │
    │    :3000        │──────────▶│    :8010        │
    │   (Express)     │           │   (FastAPI)     │
    └─────────────────┘           └─────────────────┘
```

## Services

| Service | Port | Language | Framework | Description |
|---------|------|----------|-----------|-------------|
| Go Gateway | 8080 | Go | net/http | API gateway, request routing |
| Node.js API | 3000 | JavaScript | Express | REST API, proxies to ML |
| Python ML | 8010 | Python | FastAPI | ML prediction service |

## Quick Start

```bash
# Start all services
cd examples/microservices
pactown up saas.pactown.yaml

# Test the gateway
curl http://localhost:8080/health
curl http://localhost:8080/status
```

## Startup Order

1. **Python ML** (no dependencies)
2. **Node.js API** (depends on Python ML)
3. **Go Gateway** (depends on both)

## API Endpoints

### Go Gateway (:8080)

- `GET /health` – Gateway health
- `GET /status` – Aggregated status of all services
- `GET /ml/*` – Proxied to Python ML
- `GET /api/*` – Proxied to Node.js API

### Node.js API (:3000)

- `GET /health` – Service health
- `GET /api/items` – List items
- `POST /api/items` – Create item
- `POST /api/predict` – Proxy to ML service

### Python ML (:8010)

- `GET /health` – Service health
- `GET /model/info` – Model information
- `POST /predict` – Make prediction

## Example Requests

```bash
# Get ML model info via gateway
curl http://localhost:8080/ml/model/info

# Make prediction via gateway
curl -X POST http://localhost:8080/ml/predict \
  -H "Content-Type: application/json" \
  -d '{"features": [1.0, 2.0, 3.0, 4.0]}'

# Create item via gateway
curl -X POST http://localhost:8080/api/items \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "value": 42}'

# List items
curl http://localhost:8080/api/items
```

## Requirements

- Python 3.10+
- Node.js 18+
- Go 1.21+

## File Structure

```text
microservices/
├── saas.pactown.yaml
├── README.md
└── services/
    ├── python-ml/
    │   └── README.md
    ├── node-api/
    │   └── README.md
    └── go-gateway/
        └── README.md
```
