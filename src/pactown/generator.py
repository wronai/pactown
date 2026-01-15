"""Config generator for pactown - scan folders and generate saas.pactown.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from .markpact_blocks import parse_blocks


def scan_readme(readme_path: Path) -> dict:
    """
    Scan a README.md and extract service configuration.

    Returns dict with:
    - name: service name (from folder or heading)
    - readme: relative path to README
    - port: detected port (if any)
    - health_check: detected health endpoint
    - deps: list of dependencies (markpact:deps)
    - has_run: whether it has a run block
    """
    content = readme_path.read_text()
    blocks = parse_blocks(content)

    # Extract service name from folder or first heading
    folder_name = readme_path.parent.name
    heading_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    name = folder_name

    # Detect port from run command
    port = None
    port_patterns = [
        r'--port\s+\$\{MARKPACT_PORT:-(\d+)\}',
        r'--port\s+(\d+)',
        r':(\d+)',
        r'PORT[=:-]+(\d+)',
    ]

    # Detect health check endpoint
    health_check = None
    has_run = False
    deps = []

    for block in blocks:
        if block.kind == "run":
            has_run = True
            for pattern in port_patterns:
                match = re.search(pattern, block.body)
                if match:
                    port = int(match.group(1))
                    break

        if block.kind == "deps":
            deps = [d.strip() for d in block.body.strip().split('\n') if d.strip()]

        if block.kind == "test":
            # Look for health check in tests
            if "/health" in block.body:
                health_check = "/health"
            elif "GET /" in block.body:
                health_check = "/"

    return {
        "name": name,
        "readme": str(readme_path),
        "port": port,
        "health_check": health_check,
        "deps": deps,
        "has_run": has_run,
        "title": heading_match.group(1) if heading_match else name,
    }


def scan_folder(
    folder: Path,
    recursive: bool = True,
    pattern: str = "README.md",
) -> list[dict]:
    """
    Scan a folder for README.md files and extract service configs.

    Args:
        folder: Root folder to scan
        recursive: Whether to scan subdirectories
        pattern: Filename pattern to match

    Returns:
        List of service configurations
    """
    folder = Path(folder)
    services = []

    if recursive:
        readme_files = list(folder.rglob(pattern))
    else:
        readme_files = list(folder.glob(pattern))

    for readme_path in readme_files:
        try:
            config = scan_readme(readme_path)
            if config["has_run"]:  # Only include runnable services
                services.append(config)
        except Exception as e:
            print(f"Warning: Failed to parse {readme_path}: {e}")

    return services


def generate_config(
    folder: Path,
    name: Optional[str] = None,
    base_port: int = 8000,
    output: Optional[Path] = None,
) -> dict:
    """
    Generate a pactown ecosystem configuration from a folder.

    Args:
        folder: Folder to scan for services
        name: Ecosystem name (default: folder name)
        base_port: Starting port for auto-assignment
        output: Optional path to write YAML file

    Returns:
        Generated configuration dict
    """
    folder = Path(folder)
    services = scan_folder(folder)

    if not services:
        raise ValueError(f"No runnable services found in {folder}")

    # Build config
    config = {
        "name": name or folder.name,
        "version": "0.1.0",
        "description": f"Auto-generated from {folder}",
        "base_port": base_port,
        "sandbox_root": "./.pactown-sandboxes",
        "registry": {
            "url": "http://localhost:8800",
            "namespace": "default",
        },
        "services": {},
    }

    # Assign ports and build service configs
    next_port = base_port
    for svc in services:
        port = svc["port"] or next_port
        next_port = max(next_port, port) + 1

        # Make readme path relative to output folder
        readme_rel = svc["readme"]
        if output:
            try:
                readme_rel = str(Path(svc["readme"]).relative_to(output.parent))
            except ValueError:
                pass

        service_config = {
            "readme": readme_rel,
            "port": port,
        }

        if svc["health_check"]:
            service_config["health_check"] = svc["health_check"]

        config["services"][svc["name"]] = service_config

    # Write to file if output specified
    if output:
        output = Path(output)
        with open(output, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        print(f"Generated: {output}")

    return config


def print_scan_results(folder: Path) -> None:
    """Print scan results in a readable format."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    services = scan_folder(folder)

    if not services:
        console.print(f"[yellow]No runnable services found in {folder}[/yellow]")
        return

    table = Table(title=f"Services found in {folder}")
    table.add_column("Name", style="cyan")
    table.add_column("Title")
    table.add_column("Port", style="blue")
    table.add_column("Health")
    table.add_column("Deps", style="dim")

    for svc in services:
        table.add_row(
            svc["name"],
            svc["title"][:30],
            str(svc["port"]) if svc["port"] else "auto",
            svc["health_check"] or "-",
            str(len(svc["deps"])),
        )

    console.print(table)
