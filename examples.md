---
description: Run and test pactown examples
---

# Running Pactown Examples

## SaaS Platform Example

1. Navigate to the example folder:
```bash
cd examples/saas-platform
```

2. Clean any old sandboxes:
```bash
rm -rf .pactown-sandboxes
```

// turbo
3. Start the ecosystem:
```bash
pactown up saas.pactown.yaml
```

4. Access the services:
- **Web Dashboard**: http://localhost:10002 (or check actual port in output)
- **API Docs**: http://localhost:10001/docs
- **Gateway Health**: http://localhost:10004/gateway/health

5. Stop with Ctrl+C

## Microservices Example (Polyglot)

1. Navigate:
```bash
cd examples/microservices
```

// turbo
2. Start:
```bash
pactown up saas.pactown.yaml
```

## Generate Config from Folder

1. Scan a folder to see detected services:
```bash
pactown scan ./examples/saas-platform/services
```

// turbo
2. Generate configuration:
```bash
pactown generate ./examples/saas-platform/services -o generated.pactown.yaml
```

3. Review and customize the generated file, then run:
```bash
pactown up generated.pactown.yaml
```

## Using markpact Examples

You can use existing markpact examples directly:

```bash
# From pactown root
pactown generate ../markpact/examples -o markpact-examples.pactown.yaml
pactown up markpact-examples.pactown.yaml
```

## Troubleshooting

### Port Already in Use
Pactown automatically finds free ports. If you see "Port X busy, using Y", this is normal.

### Service Won't Start
Check sandbox logs:
```bash
cat .pactown-sandboxes/<service-name>/app.log
```

### Validation Errors
```bash
pactown validate saas.pactown.yaml
```
