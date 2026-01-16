# Fast Start Demo

This example demonstrates pactown's fast startup capabilities with dependency caching.

## What This Shows

- **First run**: Dependencies are installed and cached (~5-10s)
- **Second run**: Cached venv is reused (~50-100ms)
- **Same deps = same cache**: Projects with identical dependencies share the cache

## Files

- `demo.py` - Python script demonstrating fast_run vs regular run
- `api/README.md` - Sample FastAPI service
- `api2/README.md` - Second service with same deps (will use cache)

## Usage

```bash
# Run the demo
python demo.py

# Or use pactown CLI
pactown up fast-start.pactown.yaml
```

## Expected Output

```
=== Fast Start Demo ===

Run 1 (fresh):
  Creating sandbox...
  Installing dependencies (fastapi, uvicorn)...
  ✓ Started in 5.2s

Run 2 (cached):
  ⚡ Cache hit! Reusing venv
  ✓ Started in 0.08s

Speedup: 65x faster!
```

## How It Works

```python
from pactown import ServiceRunner

runner = ServiceRunner(enable_fast_start=True)

# First run - creates and caches venv
result1 = await runner.fast_run(
    service_id="api-1",
    content=open("api/README.md").read(),
    port=8001,
)

# Second run - reuses cached venv
result2 = await runner.fast_run(
    service_id="api-2",
    content=open("api2/README.md").read(),  # Same deps!
    port=8002,
)
```

## Cache Location

```
/tmp/pactown-sandboxes/
├── .cache/
│   └── venvs/
│       └── venv_a1b2c3d4/    # Cached: fastapi + uvicorn
├── api-1/
│   └── .venv -> ../.cache/venvs/venv_a1b2c3d4
└── api-2/
    └── .venv -> ../.cache/venvs/venv_a1b2c3d4  # Same cache!
```

## Related Documentation

- [Fast Start Guide](../../docs/FAST_START.md)
- [Security Policy](../../docs/SECURITY_POLICY.md)
