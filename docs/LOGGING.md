# Logging

> 📊 Structured logging and error capture for debugging

[← Back to README](../README.md) | [User Isolation](USER_ISOLATION.md)

---

## Overview

Pactown provides detailed structured logging for:
- **Service lifecycle** - Start, stop, restart events
- **Sandbox operations** - Creation, file writes, venv setup
- **Process management** - PID, exit codes, signal handling
- **Error capture** - STDERR/STDOUT with full tracebacks

---

## Log Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed tracing (sandbox files, env vars) |
| `INFO` | Normal operations (service started, health check passed) |
| `WARNING` | Recoverable issues (rate limited, throttled) |
| `ERROR` | Failures (process died, dependency missing) |
| `CRITICAL` | System failures (disk full, no permissions) |

---

## Configuration

### Basic Setup

```python
import logging

# Configure pactown logging
logging.getLogger("pactown").setLevel(logging.INFO)
logging.getLogger("pactown.sandbox").setLevel(logging.DEBUG)
```

### File Handler

```python
import logging
from pathlib import Path

# Log to file
handler = logging.FileHandler("/var/log/pactown/sandbox.log")
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logging.getLogger("pactown").addHandler(handler)
```

---

## Log Categories

### pactown.sandbox

Sandbox creation and process management:

```
[INFO] Creating sandbox for service_123
[DEBUG] Port: 8001, README: /tmp/service_123_README.md
[DEBUG] Run command: uvicorn main:app --host 0.0.0.0 --port 8001
[DEBUG] Using venv: /tmp/pactown-sandboxes/service_123/.venv
[INFO] Process started with PID: 12345
[DEBUG] Sandbox files: ['main.py', 'requirements.txt', '.venv']
```

### pactown.security

Security policy checks:

```
[INFO] Security check for user123 starting service_456
[DEBUG] Rate limit check: 5/60 requests used
[DEBUG] Concurrent services: 2/5
[INFO] Security check passed
```

### pactown.fast_start

Dependency caching:

```
[DEBUG] Checking cache for deps: ['fastapi', 'uvicorn']
[DEBUG] Cache hit: venv_a1b2c3d4
[INFO] Using cached venv (45ms)
```

---

## Error Capture

### Process Death

When a process dies, full output is captured:

```python
# Automatic capture in sandbox_manager
if process.poll() is not None:
    exit_code = process.returncode
    stderr = process.communicate()[1].decode()
    
    # Log with interpretation
    if exit_code < 0:
        signal_name = {-9: "SIGKILL", -15: "SIGTERM"}[exit_code]
        log(f"Process killed by {signal_name}")
    
    log(f"STDERR:\n{stderr}")
```

### Error Log Files

Per-service error logs are written to disk:

```
/tmp/pactown-logs/
├── sandbox.log              # All sandbox_manager logs
├── service_123_error.log    # Error log for service_123
└── service_456_error.log    # Error log for service_456
```

**Error log format:**
```
Exit code: -15
Command: uvicorn main:app --host 0.0.0.0 --port 8001
CWD: /tmp/pactown-sandboxes/service_123
Venv: /tmp/pactown-sandboxes/service_123/.venv

--- STDERR ---
Traceback (most recent call last):
  File "main.py", line 5, in <module>
    from missing_module import something
ModuleNotFoundError: No module named 'missing_module'

--- STDOUT ---

--- FILES ---
['main.py', 'requirements.txt', '.venv']
```

---

## Log Callbacks

### on_log Parameter

Pass a callback to receive real-time logs:

```python
from pactown import ServiceRunner

def log_handler(message: str):
    print(f"[LOG] {message}")
    send_to_frontend(message)

runner = ServiceRunner()
result = await runner.run_from_content(
    service_id="my-api",
    content=markdown,
    port=8001,
    on_log=log_handler,
)
```

### Log Output

```
[LOG] Found 1 files, 2 dependencies
[LOG] Creating sandbox for service_my-api
[LOG] Starting service: service_my-api
[LOG] Process started with PID: 12345
[LOG] Waiting for server to start...
[LOG] ✓ Server responding (status 200)
```

---

## REST API Logs

### Run Response

```json
{
  "success": true,
  "port": 8001,
  "logs": [
    "Found 1 files, 2 dependencies",
    "Creating sandbox for service_123",
    "Process started with PID: 12345",
    "Waiting for server to start...",
    "✓ Server responding (status 200)",
    "✓ Project running on http://localhost:8001"
  ]
}
```

### Error Response

```json
{
  "success": false,
  "error_category": "dependency",
  "logs": [
    "Found 1 files, 2 dependencies",
    "Creating sandbox for service_123",
    "Process started with PID: 12345",
    "❌ Process killed by SIGTERM (exit code: -15)",
    "STDERR:",
    "ModuleNotFoundError: No module named 'missing_module'"
  ],
  "stderr_output": "ModuleNotFoundError: No module named 'missing_module'"
}
```

---

## Grafana + Loki Integration

For production deployments, integrate with Loki for log aggregation:

### Docker Compose

```yaml
services:
  loki:
    image: grafana/loki:2.9.0
    ports:
      - "3100:3100"

  promtail:
    image: grafana/promtail:2.9.0
    volumes:
      - ./promtail-config.yml:/etc/promtail/config.yml
      - /var/log/pactown:/var/log/pactown

  grafana:
    image: grafana/grafana:10.2.0
    ports:
      - "3001:3000"
```

### LogQL Queries

```logql
# All errors
{service="api"} |~ "(?i)(error|exception|failed|stderr)"

# Sandbox startup logs
{service="api"} |~ "(sandbox|service_|PID|Starting|Process)"

# Specific user
{service="api"} |~ "user=user123"

# Rate limiting events
{service="api"} |~ "RATE_LIMIT|CONCURRENT"
```

---

## Debugging Tips

### Enable Debug Logging

```python
import logging
logging.getLogger("pactown").setLevel(logging.DEBUG)
```

### Check Error Logs

```bash
cat /tmp/pactown-logs/service_123_error.log
```

### List Sandbox Contents

```bash
ls -la /tmp/pactown-sandboxes/service_123/
```

### Check Venv

```bash
source /tmp/pactown-sandboxes/service_123/.venv/bin/activate
pip list
```

---

## Best Practices

### 1. Structured Logging in Production

```python
import json
import logging

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger("pactown").addHandler(handler)
```

### 2. Log Rotation

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    "/var/log/pactown/sandbox.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
)
```

### 3. Alert on Errors

```python
def log_handler(message: str):
    if "❌" in message or "ERROR" in message:
        send_alert(message)
```

---

## Related Documentation

- [Security Policy](SECURITY_POLICY.md) - Anomaly logging
- [User Isolation](USER_ISOLATION.md) - Per-user log files
- [Fast Start](FAST_START.md) - Cache debug logging

[← Back to README](../README.md)
