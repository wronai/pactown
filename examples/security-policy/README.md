# Security Policy Demo

This example demonstrates pactown's security policy features for multi-tenant SaaS.

## What This Shows

- **Rate limiting** - Token bucket algorithm to prevent abuse
- **User profiles** - Tier-based resource limits (FREE/BASIC/PRO)
- **Concurrent limits** - Max services per user
- **Anomaly logging** - Track and alert on security events

## Files

- `demo.py` - Python script demonstrating security features
- `multi_tenant.py` - Multi-tenant SaaS simulation

## Usage

```bash
# Run the demo
python demo.py

# Or run the multi-tenant simulation
python multi_tenant.py
```

## Expected Output

```
=== Security Policy Demo ===

Creating user profiles...
  ✓ free_user (FREE tier): max 2 concurrent services
  ✓ pro_user (PRO tier): max 10 concurrent services

Testing rate limiting...
  Request 1: ✓ allowed
  Request 2: ✓ allowed
  ...
  Request 21: ✗ rate limited (wait 2.5s)

Testing concurrent limits...
  free_user starting service 1: ✓ allowed
  free_user starting service 2: ✓ allowed
  free_user starting service 3: ✗ limit reached (2/2)

Anomaly log:
  [RATE_LIMIT_EXCEEDED] free_user - Rate limit exceeded
  [CONCURRENT_LIMIT_EXCEEDED] free_user - Max 2 services
```

## User Tiers

| Tier | Concurrent | Memory | Requests/min |
|------|------------|--------|--------------|
| FREE | 2 | 256MB | 20 |
| BASIC | 5 | 512MB | 60 |
| PRO | 10 | 2GB | 120 |
| ENTERPRISE | 50 | 8GB | 500 |

## Code Example

```python
from pactown import SecurityPolicy, UserProfile, UserTier

# Create security policy
policy = SecurityPolicy(
    anomaly_log_path=Path("./anomalies.jsonl"),
    default_rate_limit=60,
)

# Create user profile
profile = UserProfile.from_tier("user123", UserTier.PRO)
policy.set_user_profile(profile)

# Check if user can start service
result = await policy.check_can_start_service(
    user_id="user123",
    service_id="my-api",
    port=8001,
)

if result.allowed:
    print("✓ Starting service...")
else:
    print(f"✗ Denied: {result.reason}")
```

## Related Documentation

- [Security Policy Guide](../../docs/SECURITY_POLICY.md)
- [User Isolation](../../docs/USER_ISOLATION.md)
