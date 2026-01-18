"""CLI for pactown ecosystem orchestrator."""

import sys
from pathlib import Path
from typing import Optional

import click
import yaml
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .config import load_config
from .generator import generate_config, print_scan_results
from .orchestrator import Orchestrator
from .resolver import DependencyResolver

console = Console()


def is_lolm_available() -> bool:
    from .llm import is_lolm_available as _is_lolm_available

    return _is_lolm_available()


def get_llm_status() -> dict:
    from .llm import get_llm_status as _get_llm_status

    return _get_llm_status()


def get_llm(*, verbose: bool = False):
    from .llm import get_llm as _get_llm

    return _get_llm(verbose=verbose)


def set_llm_priority(provider: str, priority: int) -> bool:
    from .llm import set_provider_priority as _set_provider_priority

    return bool(_set_provider_priority(provider, priority))


def reset_llm_provider(provider: str) -> bool:
    from .llm import reset_provider as _reset_provider

    return bool(_reset_provider(provider))


@click.group()
@click.version_option(version=__version__, prog_name="pactown")
def cli():
    """Pactown – Decentralized Service Ecosystem Orchestrator."""
    pass


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be done")
@click.option("--no-health", is_flag=True, help="Don't wait for health checks")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output")
@click.option("--sequential", "-s", is_flag=True, help="Disable parallel execution")
@click.option("--workers", "-w", default=4, type=int, help="Max parallel workers")
def up(config_path: str, dry_run: bool, no_health: bool, quiet: bool, sequential: bool, workers: int):
    """Start all services in the ecosystem."""
    try:
        config = load_config(config_path)
        orch = Orchestrator(config, base_path=Path(config_path).parent, verbose=not quiet)

        if dry_run:
            console.print(f"[bold]Dry run: {config.name}[/bold]\n")
            resolver = DependencyResolver(config)
            order = resolver.get_startup_order()

            console.print("Would start services in order:")
            for i, name in enumerate(order, 1):
                svc = config.services[name]
                deps = [d.name for d in svc.depends_on]
                deps_str = f" (deps: {', '.join(deps)})" if deps else ""
                console.print(f"  {i}. {name}:{svc.port}{deps_str}")
            return

        if not orch.validate():
            sys.exit(1)

        orch.start_all(
            wait_for_health=not no_health,
            parallel=not sequential,
            max_workers=workers,
        )

        console.print("\n[dim]Press Ctrl+C to stop all services[/dim]\n")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            orch.stop_all()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def down(config_path: str):
    """Stop all services in the ecosystem."""
    try:
        config = load_config(config_path)
        orch = Orchestrator(config, base_path=Path(config_path).parent)
        orch.stop_all()
        console.print("[green]All services stopped[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def status(config_path: str):
    """Show status of all services."""
    try:
        config = load_config(config_path)
        orch = Orchestrator(config, base_path=Path(config_path).parent)
        orch.print_status()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def validate(config_path: str):
    """Validate ecosystem configuration."""
    try:
        config = load_config(config_path)
        orch = Orchestrator(config, base_path=Path(config_path).parent)

        if orch.validate():
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
def graph(config_path: str):
    """Show dependency graph."""
    try:
        config = load_config(config_path)
        resolver = DependencyResolver(config)
        console.print(Panel(resolver.print_graph(), title="Dependency Graph"))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--name", "-n", default="my-ecosystem", help="Ecosystem name")
@click.option("--output", "-o", default="saas.pactown.yaml", help="Output file")
def init(name: str, output: str):
    """Initialize a new pactown ecosystem configuration."""
    config = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} - A pactown ecosystem",
        "base_port": 8000,
        "sandbox_root": "./.pactown-sandboxes",
        "registry": {
            "url": "http://localhost:8800",
            "namespace": "default",
        },
        "services": {
            "api": {
                "readme": "services/api/README.md",
                "port": 8001,
                "health_check": "/health",
                "env": {},
                "depends_on": [],
            },
            "web": {
                "readme": "services/web/README.md",
                "port": 8002,
                "health_check": "/",
                "depends_on": [
                    {"name": "api", "endpoint": "http://localhost:8001"},
                ],
            },
        },
    }

    output_path = Path(output)
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]Created {output_path}[/green]")
    console.print("\nNext steps:")
    console.print("  1. Create service README.md files")
    console.print("  2. Run: pactown validate saas.pactown.yaml")
    console.print("  3. Run: pactown up saas.pactown.yaml")


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--registry", "-r", default="http://localhost:8800", help="Registry URL")
def publish(config_path: str, registry: str):
    """Publish all modules to registry."""
    try:
        from .registry.client import RegistryClient

        config = load_config(config_path)
        client = RegistryClient(registry)

        if not client.health():
            console.print(
                f"[red]Error: Registry not reachable at {registry}. Start it with: make registry[/red]"
            )
            sys.exit(1)

        for name, service in config.services.items():
            readme_path = Path(config_path).parent / service.readme
            if readme_path.exists():
                result = client.publish(
                    name=name,
                    version=config.version,
                    readme_path=readme_path,
                    namespace=config.registry.namespace,
                )
                if result.get("success"):
                    console.print(f"[green]✓ Published {name}@{config.version}[/green]")
                else:
                    console.print(f"[red]✗ Failed to publish {name}: {result.get('error')}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--registry", "-r", default="http://localhost:8800", help="Registry URL")
def pull(config_path: str, registry: str):
    """Pull dependencies from registry."""
    try:
        from .registry.client import RegistryClient

        config = load_config(config_path)
        client = RegistryClient(registry)

        if not client.health():
            console.print(
                f"[red]Error: Registry not reachable at {registry}. Start it with: make registry[/red]"
            )
            sys.exit(1)

        for name, service in config.services.items():
            for dep in service.depends_on:
                if dep.name not in config.services:
                    result = client.pull(dep.name, dep.version)
                    if result:
                        console.print(f"[green]✓ Pulled {dep.name}@{dep.version}[/green]")
                    else:
                        console.print(f"[yellow]⚠ {dep.name} not found in registry[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("folder", type=click.Path(exists=True))
def scan(folder: str):
    """Scan a folder and show detected services."""
    print_scan_results(Path(folder))


@cli.command()
@click.argument("folder", type=click.Path(exists=True))
@click.option("--name", "-n", help="Ecosystem name (default: folder name)")
@click.option("--output", "-o", default="saas.pactown.yaml", help="Output file")
@click.option("--base-port", "-p", default=8000, type=int, help="Starting port")
def generate(folder: str, name: Optional[str], output: str, base_port: int):
    """Generate pactown config from a folder of README.md files.

    Example:
        pactown generate ./examples -o my-ecosystem.pactown.yaml
    """
    try:
        folder_path = Path(folder)
        output_path = Path(output)

        console.print(f"[bold]Scanning {folder_path}...[/bold]\n")
        print_scan_results(folder_path)

        console.print()

        config = generate_config(
            folder=folder_path,
            name=name,
            base_port=base_port,
            output=output_path,
        )

        console.print(f"\n[green]✓ Generated {output_path}[/green]")
        console.print(f"  Services: {len(config['services'])}")
        console.print("\nNext steps:")
        console.print(f"  pactown validate {output}")
        console.print(f"  pactown up {output}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--production", "-p", is_flag=True, help="Generate production config")
@click.option("--kubernetes", "-k", is_flag=True, help="Generate Kubernetes manifests")
def deploy(config_path: str, output: str, production: bool, kubernetes: bool):
    """Generate deployment files (Docker Compose, Kubernetes)."""
    try:
        from .deploy.base import DeploymentConfig
        from .deploy.compose import generate_compose_from_config
        from .deploy.kubernetes import KubernetesBackend

        config_path = Path(config_path)
        output_dir = Path(output)
        output_dir.mkdir(parents=True, exist_ok=True)

        if kubernetes:
            # Generate Kubernetes manifests
            from .config import load_config
            ecosystem = load_config(config_path)
            deploy_config = DeploymentConfig.for_production() if production else DeploymentConfig.for_development()
            k8s = KubernetesBackend(deploy_config)

            k8s_dir = output_dir / "kubernetes"
            k8s_dir.mkdir(exist_ok=True)

            for name, service in ecosystem.services.items():
                image = f"{deploy_config.image_prefix}/{name}:latest"
                manifests = k8s.generate_manifests(
                    service_name=name,
                    image_name=image,
                    port=service.port or 8000,
                    env=service.env,
                    health_check=service.health_check,
                )
                k8s.save_manifests(name, manifests, k8s_dir)
                console.print(f"  [green]✓[/green] {k8s_dir}/{name}.yaml")

            console.print(f"\n[green]Generated Kubernetes manifests in {k8s_dir}[/green]")
            console.print("\nDeploy with:")
            console.print(f"  kubectl apply -f {k8s_dir}/")
        else:
            # Generate Docker Compose
            generate_compose_from_config(
                config_path=config_path,
                output_dir=output_dir,
                production=production,
            )

            console.print(f"\n[green]Generated Docker Compose files in {output_dir}[/green]")
            console.print("\nRun with:")
            if production:
                console.print("  docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d")
            else:
                console.print("  docker compose up -d")
                console.print("  # or: podman-compose up -d")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cli.group()
def quadlet():
    """Podman Quadlet deployment commands for VPS production."""
    pass


@quadlet.command("shell")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
@click.option("--domain", "-d", default="localhost", help="Base domain")
@click.option("--system", is_flag=True, help="Use system-wide systemd (requires root)")
def quadlet_shell(tenant: str, domain: str, system: bool):
    """Start interactive Quadlet deployment shell.

    Example:
        pactown quadlet shell --domain pactown.com --tenant user01
    """
    from .deploy.quadlet_shell import run_shell
    run_shell(tenant_id=tenant, domain=domain, user_mode=not system)


@quadlet.command("api")
@click.option("--host", "-h", default="0.0.0.0", help="API host")
@click.option("--port", "-p", default=8800, type=int, help="API port")
@click.option("--domain", "-d", default="localhost", help="Default domain")
@click.option("--tenant", "-t", default="default", help="Default tenant")
def quadlet_api(host: str, port: int, domain: str, tenant: str):
    """Start Quadlet API server for programmatic deployments.

    Example:
        pactown quadlet api --port 8800 --domain pactown.com
    """
    from .deploy.quadlet_api import run_api
    console.print("[bold]Starting Quadlet API server...[/bold]")
    console.print(f"  Host: {host}:{port}")
    console.print(f"  Domain: {domain}")
    console.print(f"  Docs: http://{host}:{port}/docs")
    run_api(host=host, port=port, domain=domain, tenant=tenant)


@quadlet.command("generate")
@click.argument("markdown_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--domain", "-d", default="localhost", help="Domain")
@click.option("--subdomain", "-s", help="Subdomain")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
@click.option("--tls/--no-tls", default=False, help="Enable TLS")
def quadlet_generate(markdown_path: str, output: str, domain: str, subdomain: str, tenant: str, tls: bool):
    """Generate Quadlet files for a Markdown service.

    Example:
        pactown quadlet generate ./README.md --domain pactown.com --subdomain docs
    """
    from .deploy.quadlet import QuadletConfig, generate_markdown_service_quadlet

    config = QuadletConfig(
        tenant_id=tenant,
        domain=domain,
        subdomain=subdomain,
        tls_enabled=tls,
    )

    units = generate_markdown_service_quadlet(
        markdown_path=Path(markdown_path).resolve(),
        config=config,
    )

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for unit in units:
        path = output_dir / unit.filename
        path.write_text(unit.content)
        console.print(f"[green]✓ Generated: {path}[/green]")

    console.print("\n[bold]Deploy with:[/bold]")
    console.print(f"  cp {output}/*.container ~/.config/containers/systemd/tenant-{tenant}/")
    console.print("  systemctl --user daemon-reload")
    console.print(f"  systemctl --user enable --now {units[0].name}.service")


@quadlet.command("init")
@click.option("--domain", "-d", required=True, help="Domain for Traefik")
@click.option("--email", "-e", help="Email for Let's Encrypt")
@click.option("--system", is_flag=True, help="Use system-wide systemd")
def quadlet_init(domain: str, email: str, system: bool):
    """Initialize Quadlet environment with Traefik.

    Example:
        pactown quadlet init --domain pactown.com --email admin@pactown.com
    """
    from .deploy.quadlet import QuadletConfig, generate_traefik_quadlet

    config = QuadletConfig(domain=domain, user_mode=not system)

    # Create directories
    config.systemd_path.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓ Created: {config.systemd_path}[/green]")

    # Generate Traefik
    units = generate_traefik_quadlet(config)

    for unit in units:
        content = unit.content
        if email:
            content = content.replace(f"admin@{domain}", email)

        path = config.systemd_path / unit.filename
        path.write_text(content)
        console.print(f"[green]✓ Generated: {path}[/green]")

    console.print("\n[bold]Start Traefik:[/bold]")
    mode = "" if system else " --user"
    console.print(f"  systemctl{mode} daemon-reload")
    console.print(f"  systemctl{mode} enable --now traefik.service")


@quadlet.command("deploy")
@click.argument("markdown_path", type=click.Path(exists=True))
@click.option("--domain", "-d", required=True, help="Domain")
@click.option("--subdomain", "-s", help="Subdomain")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
@click.option("--tls/--no-tls", default=True, help="Enable TLS")
@click.option("--image", default="ghcr.io/pactown/markdown-server:latest", help="Container image")
def quadlet_deploy(markdown_path: str, domain: str, subdomain: str, tenant: str, tls: bool, image: str):
    """Deploy a Markdown file to VPS using Quadlet.

    Example:
        pactown quadlet deploy ./README.md --domain pactown.com --subdomain docs --tls
    """
    from .deploy.base import DeploymentConfig
    from .deploy.quadlet import QuadletBackend, QuadletConfig, generate_markdown_service_quadlet

    config = QuadletConfig(
        tenant_id=tenant,
        domain=domain,
        subdomain=subdomain,
        tls_enabled=tls,
    )

    deploy_config = DeploymentConfig.for_production()
    backend = QuadletBackend(deploy_config, config)

    if not backend.is_available():
        console.print("[red]✗ Podman 4.4+ with Quadlet support not available[/red]")
        sys.exit(1)

    md_path = Path(markdown_path).resolve()
    console.print(f"[bold]Deploying: {md_path.name}[/bold]")
    console.print(f"  Domain: {config.full_domain}")
    console.print(f"  Tenant: {tenant}")
    console.print(f"  TLS: {tls}")

    # Generate units
    units = generate_markdown_service_quadlet(md_path, config, image)

    # Save to tenant path
    config.tenant_path.mkdir(parents=True, exist_ok=True)
    for unit in units:
        unit.save(config.tenant_path)
        console.print(f"[dim]Created: {unit.filename}[/dim]")

    # Reload and start
    backend._systemctl("daemon-reload")
    service = f"{units[0].name}.service"
    backend._systemctl("enable", service)
    result = backend._systemctl("start", service)

    if result.returncode == 0:
        url = f"https://{config.full_domain}" if tls else f"http://{config.full_domain}"
        console.print("\n[green]✓ Deployed successfully![/green]")
        console.print(f"  URL: {url}")
    else:
        console.print(f"\n[red]✗ Deployment failed: {result.stderr}[/red]")
        sys.exit(1)


@quadlet.command("list")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
def quadlet_list(tenant: str):
    """List all Quadlet services for a tenant.

    Example:
        pactown quadlet list --tenant user01
    """
    from rich.table import Table

    from .deploy.base import DeploymentConfig
    from .deploy.quadlet import QuadletBackend, QuadletConfig

    config = QuadletConfig(tenant_id=tenant)
    backend = QuadletBackend(DeploymentConfig.for_production(), config)

    services = backend.list_services()

    if not services:
        console.print(f"[yellow]No services found for tenant: {tenant}[/yellow]")
        return

    table = Table(title=f"Services (tenant: {tenant})")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("State")

    for svc in services:
        status = svc["status"]
        running = "🟢 running" if status.get("running") else "🔴 stopped"
        table.add_row(svc["name"], running, status.get("state", "-"))

    console.print(table)


@quadlet.command("logs")
@click.argument("service_name")
@click.option("--tenant", "-t", default="default", help="Tenant ID")
@click.option("--lines", "-n", default=50, type=int, help="Number of lines")
def quadlet_logs(service_name: str, tenant: str, lines: int):
    """Show logs for a Quadlet service.

    Example:
        pactown quadlet logs my-service --lines 100
    """
    from .deploy.base import DeploymentConfig
    from .deploy.quadlet import QuadletBackend, QuadletConfig

    config = QuadletConfig(tenant_id=tenant)
    backend = QuadletBackend(DeploymentConfig.for_production(), config)

    output = backend.logs(service_name, tail=lines)
    console.print(output or "[dim]No logs available[/dim]")


@cli.group()
def llm():
    """LLM provider management with rotation and fallback."""
    pass


@llm.command("status")
def llm_status():
    """Show status of all LLM providers.
    
    Example:
        pactown llm status
    """
    import sys

    status = get_llm_status()

    if not status.get("lolm_installed", False):
        console.print("[yellow]lolm library not available[/yellow]")
        if status.get("lolm_import_error"):
            console.print(f"Import error: {status['lolm_import_error']}")
        if status.get("install"):
            click.echo(status["install"])
        console.print("Install/upgrade (same interpreter as pactown):")
        console.print(f"  {sys.executable} -m pip install -U pactown[llm]\n", markup=False)
        console.print("Or install directly:")
        console.print(f"  {sys.executable} -m pip install -U lolm")
        return

    if not status.get('is_available'):
        console.print("[yellow]No LLM providers available[/yellow]")
        if status.get("lolm_version"):
            console.print(f"lolm version: {status['lolm_version']}")
        if status.get("rotation_available") is False and status.get("rotation_import_error"):
            console.print(f"Rotation not available: {status['rotation_import_error']}")
        if 'error' in status:
            console.print(f"Error: {status['error']}")
        console.print("\n[dim]Tip: run `pactown llm doctor` to check Python/pip mismatch[/dim]")
        return
    
    console.print("[bold]LLM Provider Status[/bold]\n")

    if status.get("lolm_version"):
        console.print(f"[dim]lolm version: {status['lolm_version']}[/dim]")
    if status.get("rotation_available") is False:
        console.print("[dim]rotation: not available (fallback only)[/dim]")
    elif status.get("rotation_available") is True:
        console.print("[dim]rotation: enabled[/dim]")
    console.print()
    
    providers = status.get('providers', {})
    for name, info in providers.items():
        state = info.get('status', 'unknown')
        model = info.get('model', '')
        priority = info.get('priority', 100)
        
        if state == 'available':
            state_icon = "[green]●[/green]"
        elif state == 'unavailable':
            state_icon = "[red]○[/red]"
        else:
            state_icon = "[yellow]◐[/yellow]"
        
        console.print(f"  {state_icon} [bold]{name}[/bold] ({model})")
        console.print(f"      Priority: {priority}")
        
        health = info.get('health', {})
        if health:
            success_rate = health.get('success_rate', 1.0)
            total = health.get('total_requests', 0)
            rate_limits = health.get('rate_limit_hits', 0)
            console.print(f"      Requests: {total} (success: {success_rate:.1%})")
            if rate_limits > 0:
                console.print(f"      [yellow]Rate limits: {rate_limits}[/yellow]")
        
        if info.get('error'):
            console.print(f"      [red]Error: {info['error']}[/red]")
        
        console.print()


@llm.command("doctor")
def llm_doctor():
    """Diagnose LLM installation and environment issues.

    Helps detect situations where `pactown` is executed with a different
    Python interpreter than the one where you installed `lolm`.

    Example:
        pactown llm doctor
    """
    import importlib.util
    import platform
    import subprocess
    import shutil
    import sys

    from . import __version__
    from . import llm as llm_mod

    console.print("[bold]LLM Doctor[/bold]\n")

    console.print("[bold]Runtime[/bold]")
    console.print(f"  Python: {sys.executable}")
    console.print(f"  Python version: {platform.python_version()}")
    console.print(f"  pactown version: {__version__}")

    pactown_spec = importlib.util.find_spec("pactown")
    if pactown_spec and pactown_spec.origin:
        console.print(f"  pactown module: {pactown_spec.origin}")

    try:
        pip_v = subprocess.check_output(
            [sys.executable, "-m", "pip", "-V"],
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
        console.print(f"  pip: {pip_v}")
    except Exception as e:
        console.print(f"  pip: [red]error[/red] ({e})")

    pip_on_path = shutil.which("pip")
    if pip_on_path:
        console.print(f"  pip (PATH): {pip_on_path}")
    else:
        console.print("  pip (PATH): [dim]not found[/dim]")

    console.print("\n[bold]lolm[/bold]")
    info = llm_mod.get_lolm_info()
    console.print(f"  installed: {info.get('lolm_installed')}")
    if info.get("lolm_version"):
        console.print(f"  version: {info['lolm_version']}")

    lolm_spec = importlib.util.find_spec("lolm")
    if lolm_spec and lolm_spec.origin:
        console.print(f"  module: {lolm_spec.origin}")

    if info.get("lolm_import_error"):
        console.print(f"  import error: {info['lolm_import_error']}")

    console.print("\n[bold]Rotation[/bold]")
    console.print(f"  available: {info.get('rotation_available')}")
    if info.get("rotation_import_error"):
        console.print(f"  error: {info['rotation_import_error']}")

    console.print("\n[bold]Suggested fix[/bold]")
    if not info.get("lolm_installed"):
        console.print("  python -m pip install -U 'pactown[llm]'", markup=False)
        console.print(f"  {sys.executable} -m pip install -U 'pactown[llm]'", markup=False)
        console.print(f"  {sys.executable} -m pip install -U lolm")
    elif not info.get("rotation_available"):
        console.print(f"  {sys.executable} -m pip install -U lolm")
        console.print("  # rotation will be enabled automatically when supported")
    else:
        console.print("  OK")


@llm.command("priority")
@click.argument("provider")
@click.argument("priority", type=int)
def llm_priority(provider: str, priority: int):
    """Set priority for an LLM provider (lower = higher priority).
    
    Example:
        pactown llm priority openrouter 10
        pactown llm priority groq 20
    """
    if not is_lolm_available():
        console.print("[yellow]lolm library not installed[/yellow]")
        return
    
    if set_llm_priority(provider, priority):
        console.print(f"[green]✓ Set {provider} priority to {priority}[/green]")
    else:
        console.print(f"[red]Failed to set priority for {provider}[/red]")


@llm.command("reset")
@click.argument("provider")
def llm_reset(provider: str):
    """Reset an LLM provider's health metrics.
    
    Clears failure counts, rate limit history, and cooldowns.
    
    Example:
        pactown llm reset groq
    """
    if not is_lolm_available():
        console.print("[yellow]lolm library not installed[/yellow]")
        return
    
    if reset_llm_provider(provider):
        console.print(f"[green]✓ Reset {provider} health metrics[/green]")
    else:
        console.print(f"[red]Failed to reset {provider}[/red]")


@llm.command("test")
@click.option("--provider", "-p", help="Specific provider to test")
@click.option("--rotation", "-r", is_flag=True, help="Test with rotation")
def llm_test(provider: str, rotation: bool):
    """Test LLM generation with a simple prompt.
    
    Example:
        pactown llm test
        pactown llm test --provider openrouter
        pactown llm test --rotation
    """
    if not is_lolm_available():
        console.print("[yellow]lolm library not installed[/yellow]")
        return
    
    try:
        llm = get_llm()
        prompt = "Say 'Hello from Pactown!' in one short sentence."
        
        console.print("[dim]Testing LLM generation...[/dim]")
        
        if rotation:
            response = llm.generate_with_rotation(prompt, max_tokens=50)
        elif provider:
            response = llm.generate(prompt, provider=provider, max_tokens=50)
        else:
            response = llm.generate(prompt, max_tokens=50)
        
        console.print(f"[green]✓ Response:[/green] {response}")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def main(argv=None):
    """Main entry point."""
    cli(argv)


if __name__ == "__main__":
    main()
