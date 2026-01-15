# CLI Shell

Command-line interface for managing the SaaS platform. Provides admin operations and diagnostics.

## Commands

- `users list` – List all users
- `users add <name> <email>` – Add a user
- `users delete <id>` – Delete a user
- `stats` – Show platform statistics
- `health` – Check all services health

## Environment Variables

- `API_URL` – API service URL (injected by pactown)
- `DATABASE_URL` – Database service URL

---

```python markpact:deps
click
rich
httpx
```

```python markpact:file path=cli.py
#!/usr/bin/env python3
"""SaaS Platform CLI - Admin tool for managing the platform."""

import os
import sys

import click
import httpx
from rich.console import Console
from rich.table import Table

console = Console()

API_URL = os.environ.get("API_URL", "http://localhost:8001")
DATABASE_URL = os.environ.get("DATABASE_URL", "http://localhost:8003")


def api_request(method: str, path: str, json=None):
    """Make API request with error handling."""
    try:
        with httpx.Client(timeout=10) as client:
            response = client.request(method, f"{API_URL}{path}", json=json)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        console.print(f"[red]API Error: {e}[/red]")
        return None


@click.group()
@click.version_option(version="1.0.0", prog_name="saas-cli")
def cli():
    """SaaS Platform CLI - Admin tool for managing the platform."""
    pass


@cli.group()
def users():
    """User management commands."""
    pass


@users.command("list")
def list_users():
    """List all users."""
    data = api_request("GET", "/api/users")
    if not data:
        return
    
    table = Table(title="Users")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Email")
    table.add_column("Created", style="dim")
    
    for user in data.get("users", []):
        table.add_row(
            str(user["id"]),
            user["name"],
            user["email"],
            user.get("created_at", "-")[:19]
        )
    
    console.print(table)
    console.print(f"\nTotal: {data.get('count', 0)} users")


@users.command("add")
@click.argument("name")
@click.argument("email")
def add_user(name: str, email: str):
    """Add a new user."""
    data = api_request("POST", "/api/users", json={"name": name, "email": email})
    if data:
        console.print(f"[green]✓ Created user {data['id']}: {data['name']}[/green]")


@users.command("delete")
@click.argument("user_id", type=int)
@click.confirmation_option(prompt="Are you sure you want to delete this user?")
def delete_user(user_id: int):
    """Delete a user by ID."""
    data = api_request("DELETE", f"/api/users/{user_id}")
    if data:
        console.print(f"[green]✓ Deleted user {user_id}[/green]")


@users.command("get")
@click.argument("user_id", type=int)
def get_user(user_id: int):
    """Get user details."""
    data = api_request("GET", f"/api/users/{user_id}")
    if data:
        console.print(f"[cyan]ID:[/cyan] {data['id']}")
        console.print(f"[cyan]Name:[/cyan] {data['name']}")
        console.print(f"[cyan]Email:[/cyan] {data['email']}")
        console.print(f"[cyan]Created:[/cyan] {data.get('created_at', '-')}")


@cli.command()
def stats():
    """Show platform statistics."""
    data = api_request("GET", "/api/stats")
    if not data:
        return
    
    table = Table(title="Platform Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total Users", str(data.get("total_users", 0)))
    table.add_row("Active Services", str(data.get("active_services", 0)))
    
    uptime = data.get("uptime_seconds", 0)
    if uptime < 60:
        uptime_str = f"{uptime:.0f}s"
    elif uptime < 3600:
        uptime_str = f"{uptime/60:.1f}m"
    else:
        uptime_str = f"{uptime/3600:.1f}h"
    table.add_row("API Uptime", uptime_str)
    
    console.print(table)


@cli.command()
def health():
    """Check health of all services."""
    services = [
        ("API", API_URL),
        ("Database", DATABASE_URL),
    ]
    
    table = Table(title="Service Health")
    table.add_column("Service", style="cyan")
    table.add_column("URL")
    table.add_column("Status")
    
    for name, url in services:
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{url}/health")
                if response.status_code == 200:
                    status = "[green]✓ Healthy[/green]"
                else:
                    status = f"[yellow]⚠ {response.status_code}[/yellow]"
        except Exception as e:
            status = f"[red]✗ {type(e).__name__}[/red]"
        
        table.add_row(name, url, status)
    
    console.print(table)


@cli.command()
def shell():
    """Start interactive shell (placeholder)."""
    console.print("[yellow]Interactive shell not implemented yet[/yellow]")
    console.print("Use individual commands instead:")
    console.print("  saas-cli users list")
    console.print("  saas-cli stats")
    console.print("  saas-cli health")


if __name__ == "__main__":
    cli()
```

```bash markpact:run
python cli.py --help
```

```bash markpact:test
python cli.py --version
python cli.py users list
python cli.py stats
python cli.py health
```
