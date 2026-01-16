# Security Policy

> 🛡️ Rate limiting, user profiles, and anomaly logging for multi-tenant SaaS

[← Back to README](../README.md) | [Fast Start](FAST_START.md) | [User Isolation →](USER_ISOLATION.md)

---

## Overview

The Security Policy module protects your pactown deployment against:
- **DDoS attacks** via rate limiting
- **Resource exhaustion** via user quotas
- **Abuse detection** via anomaly logging
- **Server overload** via automatic throttling

---

## User Profiles

Each user has a profile with resource limits based on their tier:

| Tier | Concurrent Services | Memory | CPU | Requests/min | Services/hour |
|------|---------------------|--------|-----|--------------|---------------|
| `FREE` | 2 | 256MB | 25% | 20 | 5 |
| `BASIC` | 5 | 512MB | 50% | 60 | 20 |
| `PRO` | 10 | 2GB | 80% | 120 | 50 |
| `ENTERPRISE` | 50 | 8GB | 100% | 500 | 200 |

### Creating User Profiles

```python
from pactown import UserProfile, UserTier

# Create from tier (uses defaults)
profile = UserProfile.from_tier("user123", UserTier.PRO)

# Create with custom limits
profile = UserProfile(
    user_id="user123",
    tier=UserTier.BASIC,
    max_concurrent_services=10,  # Override default
    max_memory_mb=1024,
    max_cpu_percent=60,
    max_requests_per_minute=100,
    max_services_per_hour=30,
)
```

---

## Rate Limiting

Token bucket algorithm with configurable rates:

```python
from pactown import RateLimiter

limiter = RateLimiter(
    requests_per_minute=60,
    burst_size=10,  # Allow short bursts
)

# Check and consume token
if limiter.consume("user123"):
    # Request allowed
    process_request()
else:
    # Rate limited
    wait_time = limiter.get_wait_time("user123")
    return f"Rate limited. Retry in {wait_time:.1f}s"
```

---

## Security Checks

Before starting a service, multiple checks are performed:

```python
from pactown import SecurityPolicy, get_security_policy

policy = get_security_policy()

# Check if user can start a service
result = await policy.check_can_start_service(
    user_id="user123",
    service_id="my-api",
    port=8001,
)

if result.allowed:
    # Start the service
    if result.delay_seconds > 0:
        await asyncio.sleep(result.delay_seconds)  # Throttling
    start_service()
else:
    print(f"Denied: {result.reason}")
```

### Check Order

1. **User blocked check** - Blocked users are denied
2. **Rate limit check** - Token bucket validation
3. **Concurrent service limit** - Check against tier limit
4. **Hourly service limit** - Prevent rapid restart abuse
5. **Port restrictions** - Optional port allowlist
6. **Server load check** - Throttle during high load

---

## Resource Monitoring

Automatic throttling based on server load:

```python
from pactown import ResourceMonitor

monitor = ResourceMonitor(
    cpu_threshold=80.0,      # Start throttling at 80% CPU
    memory_threshold=85.0,   # Start throttling at 85% memory
    check_interval=5.0,      # Check every 5 seconds
)

# Check if overloaded
is_overloaded, metrics = monitor.check_overload()
if is_overloaded:
    delay = monitor.get_throttle_delay()
    print(f"Server overloaded, delay: {delay}s")
```

---

## Anomaly Logging

All security events are logged for admin review:

```python
from pactown import AnomalyType, AnomalyLogger

logger = AnomalyLogger(
    log_path=Path("/var/log/pactown-anomalies.jsonl"),
    max_events=10000,
    on_anomaly=lambda e: alert_admin(e),  # Optional callback
)

# Log an anomaly
event = logger.log(
    anomaly_type=AnomalyType.RATE_LIMIT_EXCEEDED,
    details="User exceeded rate limit",
    user_id="user123",
    service_id="my-api",
    severity="medium",
)

# Query anomalies
recent = logger.get_recent(count=100)
user_anomalies = logger.get_by_user("user123")
rate_limits = logger.get_by_type(AnomalyType.RATE_LIMIT_EXCEEDED)
```

### Anomaly Types

| Type | Description | Severity |
|------|-------------|----------|
| `RATE_LIMIT_EXCEEDED` | Too many requests | medium |
| `CONCURRENT_LIMIT_EXCEEDED` | Too many active services | medium |
| `HOURLY_LIMIT_EXCEEDED` | Too many service starts | medium |
| `SERVER_OVERLOADED` | System under heavy load | low |
| `RAPID_RESTART` | Frequent restart attempts | medium |
| `UNAUTHORIZED_ACCESS` | Invalid credentials/blocked | high |

---

## REST API Integration

### Run with User Profile

```bash
POST /runner/run
Content-Type: application/json

{
  "project_id": 123,
  "readme_content": "...",
  "port": 10001,
  "user_id": "user123",
  "user_profile": {
    "tier": "pro",
    "max_concurrent_services": 10,
    "max_memory_mb": 2048,
    "max_cpu_percent": 80,
    "max_requests_per_minute": 120,
    "max_services_per_hour": 50
  }
}
```

### Security Check Response

```json
{
  "success": false,
  "message": "Concurrent service limit reached (2/2)",
  "error_category": "permission",
  "logs": [
    "🔒 Security: Concurrent service limit reached (2/2)"
  ]
}
```

---

## Admin Dashboard

Get anomaly summary for monitoring:

```python
policy = get_security_policy()
summary = policy.get_anomaly_summary(hours=24)

print(f"Total anomalies: {summary['total_count']}")
print(f"By type: {summary['by_type']}")
print(f"Top users: {summary['top_users']}")
```

### Log File Format

```json
{"timestamp": "2026-01-16T12:00:00", "type": "RATE_LIMIT_EXCEEDED", "user_id": "user123", "details": "Rate limit exceeded", "severity": "medium"}
{"timestamp": "2026-01-16T12:01:00", "type": "CONCURRENT_LIMIT_EXCEEDED", "user_id": "user456", "details": "Max 2 concurrent services", "severity": "medium"}
```

---

## Configuration

### Global Security Policy

```python
from pactown import SecurityPolicy, set_security_policy

policy = SecurityPolicy(
    anomaly_log_path=Path("/var/log/pactown-anomalies.jsonl"),
    default_rate_limit=60,
    cpu_threshold=80.0,
    memory_threshold=85.0,
    on_anomaly=send_to_monitoring,
)

set_security_policy(policy)
```

### Per-Service Runner

```python
from pactown import ServiceRunner, SecurityPolicy

custom_policy = SecurityPolicy(default_rate_limit=30)

runner = ServiceRunner(
    sandbox_root="/tmp/sandboxes",
    security_policy=custom_policy,
)
```

---

## Best Practices

### 1. Set Appropriate Tier Limits

```python
# Free tier - strict limits for trial users
free_profile = UserProfile.from_tier("trial_user", UserTier.FREE)

# Pro tier - reasonable limits for paying customers
pro_profile = UserProfile.from_tier("paying_user", UserTier.PRO)
```

### 2. Monitor Anomalies

```python
def on_anomaly(event):
    if event.severity == "high":
        send_alert_to_slack(event)
    log_to_prometheus(event)

policy = SecurityPolicy(on_anomaly=on_anomaly)
```

### 3. Block Abusive Users

```python
policy = get_security_policy()
profile = policy.get_user_profile("abuser123")
profile.is_blocked = True
profile.blocked_reason = "Repeated abuse"
policy.set_user_profile(profile)
```

---

## Related Documentation

- [Fast Start](FAST_START.md) - Security checks work with fast_run
- [User Isolation](USER_ISOLATION.md) - Combine with Linux user isolation
- [Logging](LOGGING.md) - Detailed error logging

[← Back to README](../README.md)
