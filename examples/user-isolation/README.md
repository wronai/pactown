# User Isolation Demo

This example demonstrates pactown's Linux user-based sandbox isolation for multi-tenant SaaS.

## What This Shows

- **Linux user creation** - Each SaaS user gets a dedicated Linux user
- **Process isolation** - Different UIDs prevent cross-tenant access
- **File isolation** - Separate home directories per user
- **Migration support** - Export/import user data

## Files

- `demo.py` - Python script demonstrating user isolation
- `migration.py` - Demonstrates user data migration

## Usage

```bash
# Run the demo (works in non-root mode too)
python demo.py

# Run migration demo
python migration.py
```

## Expected Output

```
=== User Isolation Demo ===

Creating isolated users...
  ✓ user_alice -> pactown_a1b2c3d4 (UID: 60001)
  ✓ user_bob -> pactown_e5f6g7h8 (UID: 60002)

Creating sandboxes...
  ✓ user_alice/my-api: /home/pactown_users/pactown_a1b2c3d4/sandboxes/my-api
  ✓ user_bob/my-api: /home/pactown_users/pactown_e5f6g7h8/sandboxes/my-api

User statistics:
  user_alice: 1 sandbox, 0.5 MB
  user_bob: 1 sandbox, 0.5 MB

Total isolated users: 2
```

## Architecture

```
/home/pactown_users/
├── pactown_a1b2c3d4/         # user_alice (UID 60001)
│   ├── sandboxes/
│   │   └── my-api/
│   │       ├── main.py
│   │       └── .venv/
│   └── .cache/
└── pactown_e5f6g7h8/         # user_bob (UID 60002)
    ├── sandboxes/
    │   └── my-api/
    └── .cache/
```

## Code Example

```python
from pactown import UserIsolationManager, get_isolation_manager

# Get global manager
manager = get_isolation_manager()

# Create isolated user
user = manager.get_or_create_user("alice@example.com")
print(f"Linux user: {user.linux_username}")
print(f"UID: {user.linux_uid}")
print(f"Home: {user.home_dir}")

# Get sandbox path
sandbox = manager.get_sandbox_path("alice@example.com", "my-api")

# Run command as isolated user
process = manager.run_as_user(
    saas_user_id="alice@example.com",
    command="python main.py",
    cwd=sandbox,
)

# Export for migration
manager.export_user_data("alice@example.com", Path("/backup/alice.tar.gz"))
```

## Related Documentation

- [User Isolation Guide](../../docs/USER_ISOLATION.md)
- [Security Policy](../../docs/SECURITY_POLICY.md)
