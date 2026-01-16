# Fast Start

> ⚡ Dependency caching for millisecond startup times

[← Back to README](../README.md) | [Security Policy →](SECURITY_POLICY.md)

---

## Overview

Fast Start enables near-instant service startup by caching Python virtual environments based on dependency hash. When the same dependencies are used again, the cached venv is symlinked instead of recreated.

### Performance Comparison

| Scenario | Without Cache | With Cache |
|----------|---------------|------------|
| First run (2 deps) | ~5-10s | ~5-10s |
| Second run (same deps) | ~5-10s | **~50-100ms** |
| First run (6 deps) | ~15-30s | ~15-30s |
| Second run (same deps) | ~15-30s | **~100-200ms** |

---

## Quick Start

```python
from pactown import ServiceRunner

runner = ServiceRunner(
    sandbox_root="/tmp/sandboxes",
    enable_fast_start=True,  # Enabled by default
)

# First run - creates and caches venv
result = await runner.fast_run(
    service_id="my-api",
    content=markdown_content,
    port=8001,
)
print(f"Started in {result.message}")  # "Started in 150ms"

# Second run - uses cached venv
result = await runner.fast_run(
    service_id="my-api-2",
    content=markdown_content,  # Same deps
    port=8002,
)
print(f"Started in {result.message}")  # "Started in 50ms (cached)"
```

---

## Architecture

### Dependency Caching

```
/tmp/pactown-sandboxes/
├── .cache/
│   └── venvs/
│       ├── venv_a1b2c3d4/     # fastapi + uvicorn
│       │   ├── bin/python
│       │   ├── lib/
│       │   └── .deps          # ["fastapi", "uvicorn"]
│       └── venv_e5f6g7h8/     # flask + gunicorn
│           └── ...
├── service_123/
│   ├── main.py
│   └── .venv -> ../.cache/venvs/venv_a1b2c3d4  # SYMLINK!
└── service_456/
    ├── app.py
    └── .venv -> ../.cache/venvs/venv_a1b2c3d4  # Same deps = same cache
```

### Hash Calculation

```python
deps = ["fastapi", "uvicorn"]
sorted_deps = sorted(deps)  # ["fastapi", "uvicorn"]
hash = sha256("\n".join(sorted_deps))  # "a1b2c3d4..."

# Same deps in different order = same hash
deps2 = ["uvicorn", "fastapi"]
hash2 = sha256("\n".join(sorted(deps2)))  # "a1b2c3d4..." (same!)
```

---

## API Reference

### ServiceRunner.fast_run()

```python
async def fast_run(
    service_id: str,
    content: str,
    port: int,
    env: Optional[Dict[str, str]] = None,
    user_id: Optional[str] = None,
    user_profile: Optional[Dict[str, Any]] = None,
    skip_health_check: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
) -> RunResult
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `service_id` | str | Unique service identifier |
| `content` | str | Markdown content with markpact blocks |
| `port` | int | Port to run on |
| `env` | dict | Additional environment variables |
| `user_id` | str | User ID for security policy |
| `user_profile` | dict | User limits (see Security Policy) |
| `skip_health_check` | bool | Return immediately without waiting |
| `on_log` | callable | Log callback function |

**Returns:** `RunResult` with timing in message field.

### DependencyCache

```python
from pactown import DependencyCache

cache = DependencyCache(
    cache_root=Path("/tmp/cache"),
    max_cache_size=20,      # Max cached venvs
    max_age_hours=24,       # Expire after 24h
)

# Check for cached venv
cached = cache.get_cached_venv(["fastapi", "uvicorn"])
if cached:
    print(f"Cache hit: {cached.venv_path}")
else:
    # Create and cache
    cached = cache.create_and_cache(["fastapi", "uvicorn"])
```

### FastServiceStarter

```python
from pactown import FastServiceStarter

starter = FastServiceStarter(
    sandbox_root=Path("/tmp/sandboxes"),
    enable_caching=True,
    enable_pool=True,  # Pre-warmed sandboxes (optional)
)

result = await starter.fast_create_sandbox(
    service_name="my-service",
    content=markdown,
    on_log=print,
)

print(f"Ready in {result.startup_time_ms}ms")
print(f"Cache hit: {result.cache_hit}")
```

---

## Cache Management

### Get Cache Statistics

```python
runner = ServiceRunner()
stats = runner.get_cache_stats()

print(f"Cache entries: {stats['cache_entries']}")
print(f"Total size: {stats['total_size_mb']:.1f} MB")
print(f"Hit rate: {stats['hit_rate']:.1%}")
```

### Cache Cleanup

Old cache entries are automatically cleaned up based on:
- **max_cache_size**: Oldest entries removed when limit reached
- **max_age_hours**: Entries older than threshold removed

Manual cleanup:
```python
cache._cleanup_old()
```

---

## REST API

### Run with Fast Mode

```bash
POST /runner/run
Content-Type: application/json

{
  "project_id": 123,
  "readme_content": "...",
  "port": 10001,
  "fast_mode": true,
  "skip_health_check": false
}
```

**Response:**
```json
{
  "success": true,
  "port": 10001,
  "message": "Running on port 10001 (150ms)",
  "logs": [
    "⚡ Fast start mode enabled",
    "⚡ Cache hit! Reusing venv (a1b2c3d4)",
    "⚡ Sandbox ready in 45ms (cached)",
    "Starting: uvicorn main:app...",
    "✓ Running in 150ms"
  ]
}
```

### Get Cache Stats

```bash
GET /runner/cache/stats
```

**Response:**
```json
{
  "caching_enabled": true,
  "cache_entries": 5,
  "total_size_mb": 234.5,
  "oldest_entry_hours": 12.3
}
```

---

## Best Practices

### 1. Keep Dependencies Consistent

Same deps = same cache. Avoid unnecessary variations:

```markdown
# Good - will share cache
```python markpact:deps
fastapi
uvicorn
```

# Bad - different order won't matter, but extra deps break cache
```python markpact:deps
fastapi
uvicorn
requests  # Only add if needed!
```
```

### 2. Use skip_health_check for Fire-and-Forget

```python
# Return immediately, check health later
result = await runner.fast_run(
    service_id="background-worker",
    content=markdown,
    port=8001,
    skip_health_check=True,  # Returns in ~50ms
)

# Check health separately if needed
await asyncio.sleep(2)
status = runner.get_status("background-worker")
```

### 3. Pre-warm Common Stacks

```python
from pactown import FastServiceStarter

starter = FastServiceStarter(sandbox_root=Path("/tmp"))

# Pre-warm during app startup
common_stacks = [
    ["fastapi", "uvicorn"],
    ["flask", "gunicorn"],
    ["django", "gunicorn"],
]

for deps in common_stacks:
    starter.dep_cache.create_and_cache(deps)
```

---

## Troubleshooting

### Cache Not Working

1. Check cache directory permissions
2. Verify deps are exactly the same (order doesn't matter)
3. Check cache stats for hits/misses

### Slow First Run

First run always installs dependencies. This is expected.

### Symlink Errors

Ensure sandbox_root and cache are on the same filesystem.

---

## Related Documentation

- [Security Policy](SECURITY_POLICY.md) - Rate limiting works with fast_run
- [User Isolation](USER_ISOLATION.md) - Each user can have their own cache
- [Logging](LOGGING.md) - Debug cache behavior

[← Back to README](../README.md)
