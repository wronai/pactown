# User Isolation

> 👤 Linux user-based sandbox isolation for multi-tenant SaaS

[← Back to README](../README.md) | [Security Policy](SECURITY_POLICY.md) | [Logging →](LOGGING.md)

---

## Overview

User Isolation provides OS-level isolation for multi-tenant SaaS deployments by creating dedicated Linux users for each SaaS user. This enables:

- **Process isolation** - Different UIDs prevent cross-tenant access
- **File system isolation** - Separate home directories
- **Easy migration** - Tar user's home dir to migrate all projects
- **Resource limits** - Optional cgroups integration

---

## Architecture

```
SaaS User "user@example.com"
         ↓
Linux User: pactown_a1b2c3d4  (UID: 60001)
         ↓
Home Dir: /home/pactown_users/pactown_a1b2c3d4/
         ↓
Sandboxes:
├── sandboxes/service_123/
│   ├── main.py
│   └── .venv/
├── sandboxes/service_456/
│   ├── app.py
│   └── .venv/
└── .cache/
    └── venvs/
```

---

## Quick Start

```python
from pactown import UserIsolationManager, get_isolation_manager

# Get global manager
manager = get_isolation_manager()

# Create/get isolated user
user = manager.get_or_create_user("saas_user_123")
print(f"Linux user: {user.linux_username}")
print(f"UID: {user.linux_uid}")
print(f"Home: {user.home_dir}")

# Get sandbox path for a service
sandbox = manager.get_sandbox_path("saas_user_123", "my-api")
print(f"Sandbox: {sandbox}")
# -> /home/pactown_users/pactown_a1b2c3d4/sandboxes/my-api

# Run command as isolated user
process = manager.run_as_user(
    saas_user_id="saas_user_123",
    command="python main.py",
    cwd=sandbox,
    env={"PORT": "8001"},
)
```

---

## API Reference

### IsolatedUser

```python
@dataclass
class IsolatedUser:
    saas_user_id: str       # Original SaaS user ID
    linux_username: str     # Generated Linux username
    linux_uid: int          # Linux UID
    linux_gid: int          # Linux GID
    home_dir: Path          # User's home directory
    created_at: float       # Unix timestamp
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
```

### UserIsolationManager

```python
class UserIsolationManager:
    def __init__(
        self,
        users_base: Path = Path("/home/pactown_users"),
        enable_cgroups: bool = False,
    ):
        """
        Initialize isolation manager.
        
        Args:
            users_base: Base directory for user homes
            enable_cgroups: Enable cgroup resource limits
        """

    def get_or_create_user(self, saas_user_id: str) -> IsolatedUser:
        """Get or create an isolated Linux user for a SaaS user."""
    
    def get_user(self, saas_user_id: str) -> Optional[IsolatedUser]:
        """Get isolated user without creating."""
    
    def get_sandbox_path(self, saas_user_id: str, service_id: str) -> Path:
        """Get sandbox path for a specific service under user's home."""
    
    def run_as_user(
        self,
        saas_user_id: str,
        command: str,
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """Run a command as the isolated user."""
    
    def list_users(self) -> List[IsolatedUser]:
        """List all isolated users."""
    
    def get_user_stats(self, saas_user_id: str) -> Dict[str, Any]:
        """Get stats for a user's sandboxes."""
    
    def export_user_data(self, saas_user_id: str, output_path: Path) -> bool:
        """Export user's data for migration."""
    
    def import_user_data(self, saas_user_id: str, archive_path: Path) -> bool:
        """Import user's data from migration archive."""
    
    def delete_user(self, saas_user_id: str, delete_home: bool = True) -> bool:
        """Delete an isolated user."""
```

---

## Running Modes

### Root Mode

When running as root, real Linux users are created:

```python
# Running as root
manager = UserIsolationManager()
user = manager.get_or_create_user("user123")

# Creates:
# - Linux user: pactown_a1b2c3d4
# - Linux group: pactown_a1b2c3d4
# - Home directory: /home/pactown_users/pactown_a1b2c3d4
# - UID/GID: 60001/60001
```

### Non-Root Mode

When running as non-root, virtual users are tracked:

```python
# Running as regular user
manager = UserIsolationManager()
user = manager.get_or_create_user("user123")

# Creates:
# - Virtual tracking entry
# - Home directory: /home/pactown_users/pactown_a1b2c3d4
# - Uses current user's UID/GID for files
```

---

## Migration

### Export User Data

```python
manager = get_isolation_manager()

# Export to tar.gz
success = manager.export_user_data(
    saas_user_id="user123",
    output_path=Path("/backup/user123_2026-01-16.tar.gz"),
)

if success:
    print("User data exported successfully")
```

### Import User Data

```python
# On new server
manager = get_isolation_manager()

# Import from tar.gz
success = manager.import_user_data(
    saas_user_id="user123",
    archive_path=Path("/backup/user123_2026-01-16.tar.gz"),
)

if success:
    print("User data imported successfully")
```

---

## REST API Integration

### List Isolated Users

```bash
GET /runner/isolation/users
```

**Response:**
```json
{
  "users": [
    {
      "saas_user_id": "user123",
      "linux_username": "pactown_a1b2c3d4",
      "linux_uid": 60001,
      "linux_gid": 60001,
      "home_dir": "/home/pactown_users/pactown_a1b2c3d4",
      "created_at": 1705410000.0
    }
  ],
  "count": 1
}
```

### Get/Create Isolated User

```bash
GET /runner/isolation/user/user123
```

**Response:**
```json
{
  "saas_user_id": "user123",
  "linux_username": "pactown_a1b2c3d4",
  "linux_uid": 60001,
  "linux_gid": 60001,
  "home_dir": "/home/pactown_users/pactown_a1b2c3d4",
  "created_at": 1705410000.0
}
```

### Get User Statistics

```bash
GET /runner/isolation/user/user123/stats
```

**Response:**
```json
{
  "user": {
    "saas_user_id": "user123",
    "linux_username": "pactown_a1b2c3d4"
  },
  "sandbox_count": 5,
  "total_size_mb": 234.5
}
```

### Delete Isolated User

```bash
DELETE /runner/isolation/user/user123?delete_home=true
```

**Response:**
```json
{
  "success": true,
  "user_id": "user123"
}
```

---

## Docker Integration

### Dockerfile Configuration

```dockerfile
# Enable user namespace support
FROM python:3.12-slim

# Create base directory for isolated users
RUN mkdir -p /home/pactown_users && \
    chmod 755 /home/pactown_users

# Run as root to enable user creation (or use specific user)
# For production, consider running as non-root with pre-created users
```

### Docker Compose

```yaml
services:
  api:
    image: pactown-api
    volumes:
      - pactown-users:/home/pactown_users
    # For real user creation (requires privileged or specific caps)
    # cap_add:
    #   - SYS_ADMIN
    
volumes:
  pactown-users:
```

---

## Security Considerations

### Process Isolation

Each user runs with a different UID, preventing:
- Access to other users' files
- Signaling other users' processes
- Reading other users' memory

### File System Isolation

Each user has their own home directory:
```
/home/pactown_users/
├── pactown_a1b2c3d4/  # User 1 (mode 0700)
│   └── sandboxes/
└── pactown_e5f6g7h8/  # User 2 (mode 0700)
    └── sandboxes/
```

### Network Isolation

Combine with network namespaces for full isolation:
```python
# Each user gets their own network namespace
# (Requires additional configuration)
```

---

## Best Practices

### 1. Use Consistent User IDs

```python
# Use stable identifiers from your auth system
user = manager.get_or_create_user(auth_user.id)  # e.g., "auth0|123456"
```

### 2. Clean Up Unused Users

```python
# Periodically clean up inactive users
for user in manager.list_users():
    if user_is_inactive(user.saas_user_id):
        manager.delete_user(user.saas_user_id)
```

### 3. Monitor Disk Usage

```python
# Check user disk usage
for user in manager.list_users():
    stats = manager.get_user_stats(user.saas_user_id)
    if stats["total_size_mb"] > 1000:  # 1GB limit
        alert_admin(f"User {user.saas_user_id} over limit")
```

---

## Related Documentation

- [Security Policy](SECURITY_POLICY.md) - Combine with rate limiting
- [Fast Start](FAST_START.md) - Each user can have their own cache
- [Logging](LOGGING.md) - Per-user log files

[← Back to README](../README.md)
