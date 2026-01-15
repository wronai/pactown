"""Interactive shell for Podman Quadlet deployment management.

Provides a REPL-style interface for managing Quadlet deployments,
generating unit files, and deploying Markdown services.
"""

from __future__ import annotations

import cmd
import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.table import Table

from .base import DeploymentConfig
from .quadlet import (
    QuadletBackend,
    QuadletConfig,
    QuadletTemplates,
    generate_markdown_service_quadlet,
    generate_traefik_quadlet,
)

console = Console()


class QuadletShell(cmd.Cmd):
    """Interactive shell for Quadlet deployment management."""

    intro = """
╔══════════════════════════════════════════════════════════════════╗
║            🚀 Pactown Quadlet Deployment Shell                   ║
║                                                                  ║
║  Deploy Markdown services on VPS with Podman Quadlet             ║
║  Type 'help' for available commands                              ║
╚══════════════════════════════════════════════════════════════════╝
"""
    prompt = "pactown-quadlet> "

    def __init__(
        self,
        tenant_id: str = "default",
        domain: str = "localhost",
        user_mode: bool = True,
    ):
        super().__init__()
        self.quadlet_config = QuadletConfig(
            tenant_id=tenant_id,
            domain=domain,
            user_mode=user_mode,
        )
        self.deploy_config = DeploymentConfig.for_production()
        self.backend = QuadletBackend(self.deploy_config, self.quadlet_config)

        # Check availability
        if not self.backend.is_available():
            console.print("[yellow]⚠ Warning: Podman 4.4+ with Quadlet support not detected[/yellow]")
            console.print("[dim]Some features may not work. Install Podman 4.4+ for full functionality.[/dim]")

    def do_status(self, arg: str):
        """Show current configuration and status.

        Usage: status
        """
        table = Table(title="Quadlet Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Tenant ID", self.quadlet_config.tenant_id)
        table.add_row("Domain", self.quadlet_config.domain)
        table.add_row("Full Domain", self.quadlet_config.full_domain)
        table.add_row("TLS Enabled", str(self.quadlet_config.tls_enabled))
        table.add_row("User Mode", str(self.quadlet_config.user_mode))
        table.add_row("Systemd Path", str(self.quadlet_config.systemd_path))
        table.add_row("Tenant Path", str(self.quadlet_config.tenant_path))
        table.add_row("Traefik Enabled", str(self.quadlet_config.traefik_enabled))
        table.add_row("CPU Limit", self.quadlet_config.cpus)
        table.add_row("Memory Limit", self.quadlet_config.memory)

        console.print(table)

        # Podman version
        version = self.backend.get_quadlet_version()
        if version:
            console.print(f"\n[green]✓ Podman {version} available[/green]")
        else:
            console.print("\n[red]✗ Podman not available[/red]")

    def do_config(self, arg: str):
        """Configure deployment settings.

        Usage: config <setting> <value>

        Settings:
          tenant    - Tenant ID
          domain    - Base domain
          subdomain - Subdomain for service
          tls       - Enable TLS (true/false)
          cpus      - CPU limit (e.g., 0.5)
          memory    - Memory limit (e.g., 256M)

        Example:
          config domain pactown.com
          config subdomain api
          config tls true
        """
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[yellow]Usage: config <setting> <value>[/yellow]")
            return

        setting, value = parts

        if setting == "tenant":
            self.quadlet_config.tenant_id = value
        elif setting == "domain":
            self.quadlet_config.domain = value
        elif setting == "subdomain":
            self.quadlet_config.subdomain = value if value != "none" else None
        elif setting == "tls":
            self.quadlet_config.tls_enabled = value.lower() in ("true", "1", "yes")
        elif setting == "cpus":
            self.quadlet_config.cpus = value
        elif setting == "memory":
            self.quadlet_config.memory = value
        else:
            console.print(f"[red]Unknown setting: {setting}[/red]")
            return

        console.print(f"[green]✓ Set {setting} = {value}[/green]")

    def do_generate(self, arg: str):
        """Generate Quadlet unit files for a Markdown file.

        Usage: generate <markdown_path> [image]

        Example:
          generate ./README.md
          generate ./docs/API.md ghcr.io/pactown/markdown-server:latest
        """
        parts = arg.split()
        if not parts:
            console.print("[yellow]Usage: generate <markdown_path> [image][/yellow]")
            return

        markdown_path = Path(parts[0]).resolve()
        image = parts[1] if len(parts) > 1 else "ghcr.io/pactown/markdown-server:latest"

        if not markdown_path.exists():
            console.print(f"[red]File not found: {markdown_path}[/red]")
            return

        units = generate_markdown_service_quadlet(
            markdown_path=markdown_path,
            config=self.quadlet_config,
            image=image,
        )

        console.print(f"\n[bold]Generated {len(units)} unit file(s):[/bold]\n")

        for unit in units:
            console.print(Panel(
                Syntax(unit.content, "ini", theme="monokai"),
                title=f"📄 {unit.filename}",
                border_style="blue",
            ))

        # Ask to save
        if Confirm.ask("\nSave to systemd directory?"):
            tenant_path = self.quadlet_config.tenant_path
            tenant_path.mkdir(parents=True, exist_ok=True)

            for unit in units:
                path = unit.save(tenant_path)
                console.print(f"[green]✓ Saved: {path}[/green]")

            console.print("\n[dim]Run 'reload' to apply changes[/dim]")

    def do_generate_container(self, arg: str):
        """Generate a custom container Quadlet file.

        Usage: generate_container <name> <image> <port>

        Example:
          generate_container api nginx:latest 8080
          generate_container web python:3.12-slim 5000
        """
        parts = arg.split()
        if len(parts) < 3:
            console.print("[yellow]Usage: generate_container <name> <image> <port>[/yellow]")
            return

        name, image, port = parts[0], parts[1], int(parts[2])

        unit = QuadletTemplates.container(
            name=name,
            image=image,
            port=port,
            config=self.quadlet_config,
        )

        console.print(Panel(
            Syntax(unit.content, "ini", theme="monokai"),
            title=f"📄 {unit.filename}",
            border_style="blue",
        ))

        if Confirm.ask("\nSave to systemd directory?"):
            tenant_path = self.quadlet_config.tenant_path
            path = unit.save(tenant_path)
            console.print(f"[green]✓ Saved: {path}[/green]")

    def do_generate_traefik(self, arg: str):
        """Generate Traefik reverse proxy Quadlet files.

        Usage: generate_traefik

        This generates Traefik container and volume unit files
        for automatic HTTPS with Let's Encrypt.
        """
        units = generate_traefik_quadlet(self.quadlet_config)

        console.print(f"\n[bold]Generated {len(units)} unit file(s):[/bold]\n")

        for unit in units:
            console.print(Panel(
                Syntax(unit.content, "ini", theme="monokai"),
                title=f"📄 {unit.filename}",
                border_style="blue",
            ))

        if Confirm.ask("\nSave to systemd directory?"):
            systemd_path = self.quadlet_config.systemd_path
            systemd_path.mkdir(parents=True, exist_ok=True)

            for unit in units:
                path = unit.save(systemd_path)
                console.print(f"[green]✓ Saved: {path}[/green]")

    def do_list(self, arg: str):
        """List all Quadlet services for current tenant.

        Usage: list
        """
        services = self.backend.list_services()

        if not services:
            console.print("[yellow]No services found for tenant: {self.quadlet_config.tenant_id}[/yellow]")
            return

        table = Table(title=f"Services (tenant: {self.quadlet_config.tenant_id})")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("PID", style="dim")
        table.add_column("Unit File", style="dim")

        for svc in services:
            status = svc["status"]
            status_str = "🟢 running" if status.get("running") else "🔴 stopped"
            table.add_row(
                svc["name"],
                status_str,
                status.get("pid", "-"),
                svc["unit_file"],
            )

        console.print(table)

    def do_start(self, arg: str):
        """Start a Quadlet service.

        Usage: start <service_name>
        """
        if not arg:
            console.print("[yellow]Usage: start <service_name>[/yellow]")
            return

        console.print(f"Starting {arg}...")
        self.backend._systemctl("daemon-reload")
        result = self.backend._systemctl("start", f"{arg}.service")

        if result.returncode == 0:
            console.print(f"[green]✓ Started {arg}[/green]")
        else:
            console.print(f"[red]✗ Failed to start {arg}: {result.stderr}[/red]")

    def do_stop(self, arg: str):
        """Stop a Quadlet service.

        Usage: stop <service_name>
        """
        if not arg:
            console.print("[yellow]Usage: stop <service_name>[/yellow]")
            return

        result = self.backend._systemctl("stop", f"{arg}.service")

        if result.returncode == 0:
            console.print(f"[green]✓ Stopped {arg}[/green]")
        else:
            console.print(f"[red]✗ Failed to stop {arg}: {result.stderr}[/red]")

    def do_restart(self, arg: str):
        """Restart a Quadlet service.

        Usage: restart <service_name>
        """
        if not arg:
            console.print("[yellow]Usage: restart <service_name>[/yellow]")
            return

        result = self.backend._systemctl("restart", f"{arg}.service")

        if result.returncode == 0:
            console.print(f"[green]✓ Restarted {arg}[/green]")
        else:
            console.print(f"[red]✗ Failed to restart {arg}: {result.stderr}[/red]")

    def do_logs(self, arg: str):
        """Show logs for a Quadlet service.

        Usage: logs <service_name> [lines]

        Example:
          logs api
          logs api 50
        """
        parts = arg.split()
        if not parts:
            console.print("[yellow]Usage: logs <service_name> [lines][/yellow]")
            return

        service = parts[0]
        lines = int(parts[1]) if len(parts) > 1 else 50

        output = self.backend.logs(service, tail=lines)
        console.print(Panel(output or "[dim]No logs available[/dim]", title=f"Logs: {service}"))

    def do_reload(self, arg: str):
        """Reload systemd daemon to apply Quadlet changes.

        Usage: reload
        """
        console.print("Reloading systemd daemon...")
        result = self.backend._systemctl("daemon-reload")

        if result.returncode == 0:
            console.print("[green]✓ Daemon reloaded[/green]")
        else:
            console.print(f"[red]✗ Failed to reload: {result.stderr}[/red]")

    def do_deploy(self, arg: str):
        """Deploy a Markdown file as a web service.

        Usage: deploy <markdown_path> [subdomain]

        Example:
          deploy ./README.md docs
          deploy ./API.md api
        """
        parts = arg.split()
        if not parts:
            console.print("[yellow]Usage: deploy <markdown_path> [subdomain][/yellow]")
            return

        markdown_path = Path(parts[0]).resolve()
        if len(parts) > 1:
            self.quadlet_config.subdomain = parts[1]

        if not markdown_path.exists():
            console.print(f"[red]File not found: {markdown_path}[/red]")
            return

        console.print(f"\n[bold]Deploying: {markdown_path.name}[/bold]")
        console.print(f"  Domain: {self.quadlet_config.full_domain}")
        console.print(f"  Tenant: {self.quadlet_config.tenant_id}")
        console.print()

        # Generate units
        units = generate_markdown_service_quadlet(
            markdown_path=markdown_path,
            config=self.quadlet_config,
        )

        # Save units
        tenant_path = self.quadlet_config.tenant_path
        for unit in units:
            unit.save(tenant_path)
            console.print(f"[dim]Generated: {unit.filename}[/dim]")

        # Reload and start
        self.backend._systemctl("daemon-reload")

        service_name = units[0].name
        self.backend._systemctl("enable", f"{service_name}.service")
        result = self.backend._systemctl("start", f"{service_name}.service")

        if result.returncode == 0:
            url = f"https://{self.quadlet_config.full_domain}" if self.quadlet_config.tls_enabled else f"http://{self.quadlet_config.full_domain}"
            console.print("\n[green]✓ Deployed successfully![/green]")
            console.print(f"  URL: {url}")
        else:
            console.print(f"\n[red]✗ Deployment failed: {result.stderr}[/red]")

    def do_undeploy(self, arg: str):
        """Remove a deployed service.

        Usage: undeploy <service_name>
        """
        if not arg:
            console.print("[yellow]Usage: undeploy <service_name>[/yellow]")
            return

        if not Confirm.ask(f"Remove service '{arg}'?"):
            return

        result = self.backend.stop(arg)

        if result.success:
            console.print(f"[green]✓ Removed {arg}[/green]")
        else:
            console.print(f"[red]✗ Failed to remove {arg}: {result.error}[/red]")

    def do_init(self, arg: str):
        """Initialize Quadlet directories and Traefik proxy.

        Usage: init

        This creates the systemd directories and optionally
        sets up Traefik as a reverse proxy.
        """
        console.print("[bold]Initializing Quadlet deployment environment...[/bold]\n")

        # Create directories
        systemd_path = self.quadlet_config.systemd_path
        tenant_path = self.quadlet_config.tenant_path

        systemd_path.mkdir(parents=True, exist_ok=True)
        tenant_path.mkdir(parents=True, exist_ok=True)

        console.print(f"[green]✓ Created: {systemd_path}[/green]")
        console.print(f"[green]✓ Created: {tenant_path}[/green]")

        # Setup Traefik
        if Confirm.ask("\nSetup Traefik reverse proxy?"):
            units = generate_traefik_quadlet(self.quadlet_config)
            for unit in units:
                unit.save(systemd_path)
                console.print(f"[green]✓ Created: {unit.filename}[/green]")

            self.backend._systemctl("daemon-reload")
            self.backend._systemctl("enable", "traefik.service")
            self.backend._systemctl("start", "traefik.service")
            console.print("[green]✓ Traefik started[/green]")

        console.print("\n[bold green]Initialization complete![/bold green]")

    def do_export(self, arg: str):
        """Export all unit files to a directory.

        Usage: export <output_dir>
        """
        if not arg:
            console.print("[yellow]Usage: export <output_dir>[/yellow]")
            return

        output_dir = Path(arg)
        output_dir.mkdir(parents=True, exist_ok=True)

        tenant_path = self.quadlet_config.tenant_path
        if tenant_path.exists():
            for f in tenant_path.glob("*"):
                if f.is_file():
                    shutil.copy(f, output_dir)
                    console.print(f"[dim]Exported: {f.name}[/dim]")

        console.print(f"\n[green]✓ Exported to: {output_dir}[/green]")

    def do_help(self, arg: str):
        """Show help for commands."""
        if arg:
            super().do_help(arg)
        else:
            console.print(Panel("""
[bold cyan]Deployment Commands:[/bold cyan]
  deploy      - Deploy a Markdown file as a web service
  undeploy    - Remove a deployed service
  start       - Start a service
  stop        - Stop a service
  restart     - Restart a service

[bold cyan]Generation Commands:[/bold cyan]
  generate           - Generate Quadlet files for Markdown
  generate_container - Generate custom container Quadlet
  generate_traefik   - Generate Traefik reverse proxy

[bold cyan]Management Commands:[/bold cyan]
  status   - Show configuration and status
  config   - Configure deployment settings
  list     - List all services
  logs     - Show service logs
  reload   - Reload systemd daemon
  init     - Initialize Quadlet environment
  export   - Export unit files

[bold cyan]Other:[/bold cyan]
  help     - Show this help
  quit     - Exit the shell
""", title="Available Commands"))

    def do_quit(self, arg: str):
        """Exit the shell."""
        console.print("[dim]Goodbye![/dim]")
        return True

    def do_exit(self, arg: str):
        """Exit the shell."""
        return self.do_quit(arg)

    def do_EOF(self, arg: str):
        """Exit on Ctrl+D."""
        console.print()
        return self.do_quit(arg)

    def default(self, line: str):
        """Handle unknown commands."""
        console.print(f"[red]Unknown command: {line}[/red]")
        console.print("[dim]Type 'help' for available commands[/dim]")

    def emptyline(self):
        """Do nothing on empty line."""
        pass


def run_shell(
    tenant_id: str = "default",
    domain: str = "localhost",
    user_mode: bool = True,
):
    """Run the interactive Quadlet shell."""
    shell = QuadletShell(
        tenant_id=tenant_id,
        domain=domain,
        user_mode=user_mode,
    )
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")


if __name__ == "__main__":
    run_shell()
