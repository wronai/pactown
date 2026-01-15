"""Orchestrator for managing pactown service ecosystems."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import EcosystemConfig, load_config
from .network import ServiceRegistry
from .resolver import DependencyResolver
from .sandbox_manager import SandboxManager, ServiceProcess

console = Console()


@dataclass
class ServiceHealth:
    """Health status of a service."""
    name: str
    healthy: bool
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error: Optional[str] = None


class Orchestrator:
    """Orchestrates the lifecycle of a pactown ecosystem."""

    def __init__(
        self,
        config: EcosystemConfig,
        base_path: Optional[Path] = None,
        verbose: bool = True,
        dynamic_ports: bool = True,
    ):
        self.config = config
        self.base_path = base_path or Path.cwd()
        self.verbose = verbose
        self.dynamic_ports = dynamic_ports
        self.resolver = DependencyResolver(config)
        self.sandbox_manager = SandboxManager(config.sandbox_root)
        self._running: dict[str, ServiceProcess] = {}

        # Service registry for dynamic port allocation and discovery
        registry_path = Path(config.sandbox_root) / ".pactown-services.json"
        self.service_registry = ServiceRegistry(storage_path=registry_path)

    @classmethod
    def from_file(
        cls,
        config_path: str | Path,
        verbose: bool = True,
        dynamic_ports: bool = True,
    ) -> "Orchestrator":
        """Create orchestrator from configuration file."""
        config_path = Path(config_path)
        config = load_config(config_path)
        return cls(config, base_path=config_path.parent, verbose=verbose, dynamic_ports=dynamic_ports)

    def _get_readme_path(self, service_name: str) -> Path:
        """Get the README path for a service."""
        service = self.config.services[service_name]
        readme_path = self.base_path / service.readme
        if not readme_path.exists():
            raise FileNotFoundError(f"README not found: {readme_path}")
        return readme_path

    def validate(self) -> bool:
        """Validate the ecosystem configuration."""
        issues = self.resolver.validate()

        for name, service in self.config.services.items():
            readme_path = self.base_path / service.readme
            if not readme_path.exists():
                issues.append(f"README not found for '{name}': {readme_path}")

        if issues:
            console.print("[red]Validation failed:[/red]")
            for issue in issues:
                console.print(f"  • {issue}")
            return False

        console.print("[green]✓ Ecosystem configuration is valid[/green]")
        return True

    def start_service(self, service_name: str) -> ServiceProcess:
        """Start a single service."""
        if service_name not in self.config.services:
            raise ValueError(f"Unknown service: {service_name}")

        service = self.config.services[service_name]
        readme_path = self._get_readme_path(service_name)

        # Register service and get allocated port
        if self.dynamic_ports:
            endpoint = self.service_registry.register(
                name=service_name,
                preferred_port=service.port,
                health_check=service.health_check,
            )
            actual_port = endpoint.port

            if self.verbose and actual_port != service.port:
                console.print(f"  [yellow]Port {service.port} busy, using {actual_port}[/yellow]")
        else:
            actual_port = service.port

        # Get dependencies from config
        dep_names = [d.name for d in service.depends_on]

        # Build environment with service discovery
        env = self.service_registry.get_environment(service_name, dep_names)

        # Add any extra env from config
        env.update(service.env)
        env["PACTOWN_ECOSYSTEM"] = self.config.name

        # Override port in service config for this run
        service_copy = service
        if actual_port != service.port:
            from dataclasses import replace
            service_copy = replace(service, port=actual_port)

        process = self.sandbox_manager.start_service(
            service_copy, readme_path, env, verbose=self.verbose
        )
        self._running[service_name] = process
        return process

    def start_all(
        self,
        wait_for_health: bool = True,
        parallel: bool = True,
        max_workers: int = 4,
    ) -> dict[str, ServiceProcess]:
        """
        Start all services in dependency order.

        Args:
            wait_for_health: Wait for health checks
            parallel: Use parallel execution for independent services
            max_workers: Max parallel workers
        """
        if parallel:
            return self._start_all_parallel(wait_for_health, max_workers)
        else:
            return self._start_all_sequential(wait_for_health)

    def _start_all_sequential(self, wait_for_health: bool = True) -> dict[str, ServiceProcess]:
        """Start all services sequentially in dependency order."""
        order = self.resolver.get_startup_order()

        if self.verbose:
            console.print(f"\n[bold]Starting ecosystem: {self.config.name}[/bold]")
            console.print(f"Startup order: {' → '.join(order)}\n")

        for name in order:
            try:
                self.start_service(name)

                if wait_for_health:
                    service = self.config.services[name]
                    if service.health_check:
                        self._wait_for_health(name, timeout=service.timeout)
                    else:
                        time.sleep(1)

            except Exception as e:
                console.print(f"[red]Failed to start {name}: {e}[/red]")
                self.stop_all()
                raise

        if self.verbose:
            self.print_status()

        return self._running

    def _start_all_parallel(
        self,
        wait_for_health: bool = True,
        max_workers: int = 4,
    ) -> dict[str, ServiceProcess]:
        """
        Start services in parallel waves based on dependencies.

        Services with no unmet dependencies start together in parallel.
        Once a wave completes, the next wave starts.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if self.verbose:
            console.print(f"\n[bold]Starting ecosystem: {self.config.name} (parallel)[/bold]")

        # Build dependency map
        deps_map: dict[str, list[str]] = {}
        for name, service in self.config.services.items():
            deps_map[name] = [d.name for d in service.depends_on if d.name in self.config.services]

        started = set()
        remaining = set(self.config.services.keys())
        wave_num = 0

        while remaining:
            # Find services ready to start (all deps satisfied)
            ready = [
                name for name in remaining
                if all(d in started for d in deps_map.get(name, []))
            ]

            if not ready:
                raise ValueError(f"Cannot resolve dependencies for: {remaining}")

            wave_num += 1
            if self.verbose:
                console.print(f"\n[cyan]Wave {wave_num}:[/cyan] {', '.join(ready)}")

            # Start ready services in parallel
            wave_results = {}
            wave_errors = {}

            with ThreadPoolExecutor(max_workers=min(max_workers, len(ready))) as executor:
                futures = {}

                for name in ready:
                    future = executor.submit(self._start_service_with_health, name, wait_for_health)
                    futures[future] = name

                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        proc = future.result()
                        wave_results[name] = proc
                        self._running[name] = proc
                        started.add(name)
                        remaining.remove(name)
                    except Exception as e:
                        wave_errors[name] = str(e)
                        remaining.remove(name)

            # Report wave results
            for name in wave_results:
                if self.verbose:
                    console.print(f"  [green]✓[/green] {name} started")

            for name, error in wave_errors.items():
                console.print(f"  [red]✗[/red] {name}: {error}")

            # Stop on any failure
            if wave_errors:
                console.print("\n[red]Stopping due to errors...[/red]")
                self.stop_all()
                raise RuntimeError(f"Failed to start services: {wave_errors}")

        if self.verbose:
            console.print()
            self.print_status()

        return self._running

    def _start_service_with_health(self, service_name: str, wait_for_health: bool) -> ServiceProcess:
        """Start a service and optionally wait for health check."""
        proc = self.start_service(service_name)

        if wait_for_health:
            service = self.config.services[service_name]
            if service.health_check:
                self._wait_for_health(service_name, timeout=service.timeout)
            else:
                time.sleep(0.5)

        return proc

    def stop_service(self, service_name: str) -> bool:
        """Stop a single service."""
        if service_name not in self._running:
            return False

        if self.verbose:
            console.print(f"Stopping {service_name}...")

        success = self.sandbox_manager.stop_service(service_name)
        if success:
            del self._running[service_name]
        return success

    def stop_all(self) -> None:
        """Stop all services in reverse dependency order."""
        order = self.resolver.get_shutdown_order()

        if self.verbose:
            console.print(f"\n[bold]Stopping ecosystem: {self.config.name}[/bold]")

        for name in order:
            if name in self._running:
                self.stop_service(name)
            # Unregister from service registry
            self.service_registry.unregister(name)

        self.sandbox_manager.stop_all()
        self._running.clear()

    def restart_service(self, service_name: str) -> ServiceProcess:
        """Restart a single service."""
        self.stop_service(service_name)
        time.sleep(0.5)
        return self.start_service(service_name)

    def check_health(self, service_name: str) -> ServiceHealth:
        """Check health of a service."""
        if service_name not in self.config.services:
            return ServiceHealth(name=service_name, healthy=False, error="Unknown service")

        service = self.config.services[service_name]

        if service_name not in self._running:
            return ServiceHealth(name=service_name, healthy=False, error="Not running")

        if not self._running[service_name].is_running:
            return ServiceHealth(name=service_name, healthy=False, error="Process died")

        if not service.health_check:
            return ServiceHealth(name=service_name, healthy=True)

        # Get actual port from registry (may differ from config if dynamic)
        endpoint = self.service_registry.get(service_name)
        port = endpoint.port if endpoint else service.port
        url = f"http://localhost:{port}{service.health_check}"

        try:
            start = time.time()
            response = httpx.get(url, timeout=5.0)
            elapsed = (time.time() - start) * 1000

            return ServiceHealth(
                name=service_name,
                healthy=response.status_code < 400,
                status_code=response.status_code,
                response_time_ms=elapsed,
            )
        except Exception as e:
            return ServiceHealth(
                name=service_name,
                healthy=False,
                error=str(e),
            )

    def _wait_for_health(self, service_name: str, timeout: int = 60) -> bool:
        """Wait for a service to become healthy."""
        service = self.config.services[service_name]

        if not service.health_check:
            return True

        # Get actual port from registry
        endpoint = self.service_registry.get(service_name)
        port = endpoint.port if endpoint else service.port
        url = f"http://localhost:{port}{service.health_check}"
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code < 400:
                    if self.verbose:
                        console.print(f"  [green]✓[/green] {service_name} is healthy")
                    return True
            except Exception:
                pass
            time.sleep(0.5)

        console.print(f"  [yellow]⚠[/yellow] {service_name} health check timed out")
        return False

    def print_status(self) -> None:
        """Print status of all services."""
        table = Table(title=f"Ecosystem: {self.config.name}")
        table.add_column("Service", style="cyan")
        table.add_column("Port", style="blue")
        table.add_column("Status", style="green")
        table.add_column("PID")
        table.add_column("Health")

        for name, service in self.config.services.items():
            # Get actual port from registry
            endpoint = self.service_registry.get(name)
            actual_port = endpoint.port if endpoint else service.port

            if name in self._running:
                proc = self._running[name]
                running = "🟢 Running" if proc.is_running else "🔴 Stopped"
                pid = str(proc.pid)

                health = self.check_health(name)
                if health.healthy:
                    health_str = f"✓ {health.response_time_ms:.0f}ms" if health.response_time_ms else "✓"
                else:
                    health_str = health.error or "✗"
            else:
                running = "⚪ Not started"
                pid = "-"
                health_str = "-"
                actual_port = service.port  # Use config port if not registered

            table.add_row(
                name,
                str(actual_port) if actual_port else "-",
                running,
                pid,
                health_str,
            )

        console.print(table)

    def print_graph(self) -> None:
        """Print dependency graph."""
        console.print(Panel(self.resolver.print_graph(), title="Dependency Graph"))

    def get_logs(self, service_name: str, lines: int = 100) -> Optional[str]:
        """Get recent logs from a service (if available)."""
        if service_name not in self._running:
            return None

        proc = self._running[service_name]
        if proc.process and proc.process.stdout:
            return proc.process.stdout.read()
        return None


def run_ecosystem(config_path: str | Path, wait: bool = True) -> Orchestrator:
    """Convenience function to start an ecosystem."""
    orch = Orchestrator.from_file(config_path)

    if not orch.validate():
        raise ValueError("Invalid ecosystem configuration")

    orch.start_all()

    if wait:
        try:
            console.print("\n[dim]Press Ctrl+C to stop all services[/dim]\n")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            orch.stop_all()

    return orch
