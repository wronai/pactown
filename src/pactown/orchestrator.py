"""Orchestrator for managing pactown service ecosystems."""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable
import httpx

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

from .config import EcosystemConfig, load_config
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
    ):
        self.config = config
        self.base_path = base_path or Path.cwd()
        self.verbose = verbose
        self.resolver = DependencyResolver(config)
        self.sandbox_manager = SandboxManager(config.sandbox_root)
        self._running: dict[str, ServiceProcess] = {}
    
    @classmethod
    def from_file(cls, config_path: str | Path, verbose: bool = True) -> "Orchestrator":
        """Create orchestrator from configuration file."""
        config_path = Path(config_path)
        config = load_config(config_path)
        return cls(config, base_path=config_path.parent, verbose=verbose)
    
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
        env = self.resolver.get_environment(service_name)
        
        process = self.sandbox_manager.start_service(
            service, readme_path, env, verbose=self.verbose
        )
        self._running[service_name] = process
        return process
    
    def start_all(self, wait_for_health: bool = True) -> dict[str, ServiceProcess]:
        """Start all services in dependency order."""
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
        
        url = f"http://localhost:{service.port}{service.health_check}"
        
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
        
        url = f"http://localhost:{service.port}{service.health_check}"
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
            
            table.add_row(
                name,
                str(service.port) if service.port else "-",
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
