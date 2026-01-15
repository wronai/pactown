# Config Generator

> **See also:** [README](../README.md) | [Specification](SPECIFICATION.md) | [Network](NETWORK.md) | [Configuration](CONFIGURATION.md)

Automatically generate `saas.pactown.yaml` by scanning a folder of markpact README files.

## Quick Start

```bash
# Scan folder to see detected services
pactown scan ./examples

# Generate config from folder
pactown generate ./examples -o my-ecosystem.pactown.yaml

# With custom name and port
pactown generate ./examples --name my-platform --base-port 9000 -o config.yaml
```

## Example

Given this folder structure:

```
examples/
├── api/
│   └── README.md       # markpact service
├── database/
│   └── README.md       # markpact service
└── frontend/
    └── README.md       # markpact service
```

Running:

```bash
pactown generate ./examples -o ecosystem.pactown.yaml
```

Produces:

```yaml
name: examples
version: 0.1.0
description: Auto-generated from examples
base_port: 8000
sandbox_root: ./.pactown-sandboxes

registry:
  url: http://localhost:8800
  namespace: default

services:
  api:
    readme: examples/api/README.md
    port: 8001
    health_check: /health
  
  database:
    readme: examples/database/README.md
    port: 8000
    health_check: /health
  
  frontend:
    readme: examples/frontend/README.md
    port: 8002
    health_check: /
```

## How It Works

The generator:

1. **Scans** for `README.md` files recursively
2. **Parses** markpact blocks using `pactown.markpact_blocks.parse_blocks()`
3. **Extracts**:
   - Service name (from folder name)
   - Port (from `markpact:run` command)
   - Health check (from `markpact:test http` blocks)
   - Dependencies (from `markpact:deps`)
4. **Assigns** ports automatically if not detected
5. **Writes** YAML configuration

**Source:** [`generator.py`](../src/pactown/generator.py)

## CLI Commands

### `pactown scan`

Show detected services without generating config:

```bash
$ pactown scan ./examples/saas-platform/services

        Services found in ./examples/saas-platform/services
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━┓
┃ Name     ┃ Title            ┃ Port ┃ Health  ┃ Deps ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━┩
│ api      │ API Backend      │ auto │ /health │ 2    │
│ database │ Database Service │ 8003 │ /health │ 0    │
│ gateway  │ API Gateway      │ 8000 │ /health │ 3    │
│ web      │ Web Frontend     │ 8002 │ /health │ 0    │
└──────────┴──────────────────┴──────┴─────────┴──────┘
```

### `pactown generate`

Generate configuration file:

```bash
pactown generate FOLDER [OPTIONS]

Options:
  -n, --name TEXT       Ecosystem name (default: folder name)
  -o, --output TEXT     Output file (default: saas.pactown.yaml)
  -p, --base-port INT   Starting port (default: 8000)
```

## Python API

```python
from pactown.generator import scan_folder, generate_config, scan_readme

# Scan single README
config = scan_readme(Path("./api/README.md"))
print(config)
# {
#   'name': 'api',
#   'readme': './api/README.md',
#   'port': 8001,
#   'health_check': '/health',
#   'deps': ['fastapi', 'uvicorn'],
#   'has_run': True,
#   'title': 'API Backend'
# }

# Scan folder
services = scan_folder(Path("./examples"))
for svc in services:
    print(f"{svc['name']}: port={svc['port']}")

# Generate full config
config = generate_config(
    folder=Path("./examples"),
    name="my-platform",
    base_port=9000,
    output=Path("config.yaml"),
)
```

## Detection Logic

### Port Detection

The generator looks for port in `markpact:run` blocks:
 
````markdown
```bash markpact:run
uvicorn main:app --port ${MARKPACT_PORT:-8001}
```
````
Patterns matched:
- `--port ${MARKPACT_PORT:-8001}` → 8001
- `--port 8080` → 8080
- `:3000` → 3000
- `PORT=5000` → 5000

### Health Check Detection

Extracted from `markpact:test http` blocks:
 
````markdown
```http markpact:test
GET /health EXPECT 200
GET /api/users EXPECT 200
```
````
Detects: `/health` (preferred) or first `GET /` endpoint.

### Dependencies

From `markpact:deps` blocks:
 
````markdown
```python markpact:deps
fastapi
uvicorn
httpx
```
````
## Limitations

- **No dependency inference** – doesn't detect cross-service dependencies
- **Simple port detection** – may miss complex port configurations
- **Flat structure** – all services at same level (no sub-ecosystems)

For complex dependencies, manually edit the generated YAML.

## Best Practices

1. **Use consistent structure** – one service per folder with README.md
2. **Add health checks** – include `markpact:test http` blocks
3. **Use MARKPACT_PORT** – `--port ${MARKPACT_PORT:-8001}` for flexibility
4. **Review generated config** – add dependencies manually if needed
