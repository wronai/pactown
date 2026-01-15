"""CLI for pactown ecosystem orchestrator."""

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
import yaml

from . import __version__
from .config import EcosystemConfig, load_config
from .orchestrator import Orchestrator, run_ecosystem
from .resolver import DependencyResolver
from .generator import scan_folder, generate_config, print_scan_results


console = Console()


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
def up(config_path: str, dry_run: bool, no_health: bool, quiet: bool):
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
        
        orch.start_all(wait_for_health=not no_health)
        
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
        console.print(f"\nNext steps:")
        console.print(f"  pactown validate {output}")
        console.print(f"  pactown up {output}")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def main(argv=None):
    """Main entry point."""
    cli(argv)


if __name__ == "__main__":
    main()
