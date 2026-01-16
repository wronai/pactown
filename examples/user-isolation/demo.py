#!/usr/bin/env python3
"""
User Isolation Demo - Demonstrates Linux user-based sandbox isolation.

Usage:
    python demo.py
"""
import tempfile
from pathlib import Path

# Add pactown to path if running from source
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pactown import UserIsolationManager


def main():
    print("=" * 50)
    print("👤 User Isolation Demo")
    print("=" * 50)
    print()
    
    # Use temp directory for demo
    with tempfile.TemporaryDirectory() as tmpdir:
        users_base = Path(tmpdir)
        
        # Create isolation manager
        manager = UserIsolationManager(users_base=users_base)
        
        # Create isolated users
        print("Creating isolated users...")
        
        users = [
            ("alice@example.com", "Alice"),
            ("bob@example.com", "Bob"),
            ("charlie@example.com", "Charlie"),
        ]
        
        for email, name in users:
            user = manager.get_or_create_user(email)
            print(f"  ✓ {name} -> {user.linux_username} (UID: {user.linux_uid})")
        
        print()
        
        # Create sandboxes for each user
        print("Creating sandboxes...")
        
        for email, name in users:
            sandbox = manager.get_sandbox_path(email, "my-api")
            
            # Create a test file in sandbox
            (sandbox / "main.py").write_text(f'print("Hello from {name}!")')
            
            print(f"  ✓ {name}/my-api: {sandbox}")
        
        print()
        
        # Show user statistics
        print("User statistics:")
        
        for email, name in users:
            stats = manager.get_user_stats(email)
            print(f"  {name}: {stats['sandbox_count']} sandbox(es), {stats['total_size_mb']:.2f} MB")
        
        print()
        
        # List all users
        all_users = manager.list_users()
        print(f"Total isolated users: {len(all_users)}")
        
        print()
        
        # Demonstrate running as user (non-root mode)
        print("Running command as isolated user...")
        
        alice = manager.get_user("alice@example.com")
        sandbox = manager.get_sandbox_path("alice@example.com", "my-api")
        
        process = manager.run_as_user(
            saas_user_id="alice@example.com",
            command="python main.py",
            cwd=sandbox,
        )
        
        stdout, stderr = process.communicate(timeout=5)
        print(f"  Output: {stdout.decode().strip()}")
        
        print()
        
        # Demonstrate export
        print("Export/Import demonstration...")
        
        export_path = Path(tmpdir) / "alice_backup.tar.gz"
        success = manager.export_user_data("alice@example.com", export_path)
        
        if success:
            print(f"  ✓ Exported alice to {export_path}")
            print(f"  Archive size: {export_path.stat().st_size / 1024:.1f} KB")
        else:
            print("  ✗ Export failed (may require root)")
        
        print()
        print("=" * 50)
        print("Demo complete!")
        print("=" * 50)


if __name__ == "__main__":
    main()
