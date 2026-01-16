"""
High-level service runner for markpact projects.

Provides a simple API to run services directly from markdown content
with health checks, restart support, and endpoint testing.
"""

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import httpx


def kill_process_on_port(port: int) -> bool:
    """Kill any process using the specified port.
    
    Uses /proc filesystem to find processes (works in minimal containers).
    Returns True if a process was killed, False otherwise.
    """
    killed = False
    
    # Method 1: Check /proc/net/tcp for listening sockets
    try:
        hex_port = f"{port:04X}"
        with open("/proc/net/tcp", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                local_addr = parts[1]
                if local_addr.endswith(f":{hex_port}"):
                    # Found a socket on this port, find the inode
                    inode = parts[9]
                    # Search for process with this inode
                    for pid_dir in os.listdir("/proc"):
                        if not pid_dir.isdigit():
                            continue
                        try:
                            fd_dir = f"/proc/{pid_dir}/fd"
                            for fd in os.listdir(fd_dir):
                                try:
                                    link = os.readlink(f"{fd_dir}/{fd}")
                                    if f"socket:[{inode}]" in link:
                                        pid = int(pid_dir)
                                        if pid > 1:  # Don't kill init
                                            os.kill(pid, signal.SIGKILL)
                                            killed = True
                                except (OSError, PermissionError):
                                    pass
                        except (OSError, PermissionError):
                            pass
    except (FileNotFoundError, PermissionError):
        pass
    
    # Method 2: Fallback - try lsof/fuser if available
    if not killed:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid in result.stdout.strip().split('\n'):
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        killed = True
                    except (ProcessLookupError, ValueError):
                        pass
        except FileNotFoundError:
            pass
    
    if not killed:
        try:
            result = subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
            killed = result.returncode == 0
        except FileNotFoundError:
            pass
    
    # Give the OS a moment to clean up
    if killed:
        time.sleep(0.5)
    
    return killed

from .config import ServiceConfig
from .markpact_blocks import parse_blocks, Block
from .sandbox_manager import SandboxManager, ServiceProcess


@dataclass
class RunResult:
    """Result of running a service."""
    success: bool
    port: int
    pid: Optional[int] = None
    message: str = ""
    logs: List[str] = field(default_factory=list)
    service_name: Optional[str] = None
    sandbox_path: Optional[Path] = None


@dataclass
class EndpointTestResult:
    """Result of testing an endpoint."""
    endpoint: str
    success: bool
    status: Optional[int] = None
    error: Optional[str] = None
    url: str = ""
    response_time_ms: Optional[float] = None


@dataclass
class ValidationResult:
    """Result of validating markpact content."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    file_count: int = 0
    deps_count: int = 0
    has_run: bool = False
    has_health: bool = False


class ServiceRunner:
    """
    High-level service runner for markpact projects.
    
    Usage:
        runner = ServiceRunner("/tmp/sandboxes")
        result = await runner.run_from_content(
            service_id="my-service",
            content="# My API\\n```python markpact:file path=main.py...",
            port=8000
        )
        if result.success:
            print(f"Running on port {result.port}")
    """
    
    def __init__(
        self,
        sandbox_root: str | Path = "/tmp/pactown-sandboxes",
        default_health_check: str = "/health",
        health_timeout: int = 10,
    ):
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.sandbox_manager = SandboxManager(self.sandbox_root)
        self.default_health_check = default_health_check
        self.health_timeout = health_timeout
        self._services: Dict[str, str] = {}  # external_id -> service_name
    
    def validate_content(self, content: str) -> ValidationResult:
        """Validate markpact content before running."""
        errors = []
        
        try:
            blocks = parse_blocks(content)
        except Exception as e:
            return ValidationResult(valid=False, errors=[f"Parse error: {e}"])
        
        file_count = sum(1 for b in blocks if b.kind == "file")
        deps_count = sum(
            len(b.body.strip().split('\n')) 
            for b in blocks if b.kind == "deps"
        )
        has_run = any(b.kind == "run" for b in blocks)
        has_health = any(b.kind == "health" or b.kind == "healthcheck" for b in blocks)
        
        if file_count == 0:
            errors.append("No files found. Add ```python markpact:file path=main.py``` blocks.")
        
        if not has_run:
            errors.append("No run command. Add ```bash markpact:run``` block.")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            file_count=file_count,
            deps_count=deps_count,
            has_run=has_run,
            has_health=has_health,
        )
    
    async def run_from_content(
        self,
        service_id: str,
        content: str,
        port: int,
        env: Optional[Dict[str, str]] = None,
        restart_if_running: bool = True,
        wait_for_health: bool = True,
        health_timeout: Optional[int] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        """
        Run a service directly from markdown content.
        
        Args:
            service_id: Unique identifier for the service
            content: Markdown content with markpact blocks
            port: Port to run the service on
            env: Additional environment variables
            restart_if_running: Restart if already running
            wait_for_health: Wait for health check to pass
            health_timeout: Health check timeout (default: self.health_timeout)
            on_log: Callback for log messages
        
        Returns:
            RunResult with success status, logs, and service info
        """
        logs: List[str] = []
        service_name = f"service_{service_id}"
        
        def log(msg: str):
            logs.append(msg)
            if on_log:
                on_log(msg)
        
        # Check if already running (tracked by sandbox manager)
        status = self.sandbox_manager.get_status(service_name)
        if status and status.get("running"):
            if restart_if_running:
                log(f"Service {service_name} is running, restarting...")
                try:
                    self.sandbox_manager.stop_service(service_name)
                    self.sandbox_manager.clean_sandbox(service_name)
                    log("Previous instance stopped")
                except Exception as e:
                    log(f"Warning: could not stop previous instance: {e}")
            else:
                return RunResult(
                    success=False,
                    port=port,
                    message="Service is already running",
                    logs=logs,
                    service_name=service_name,
                )
        
        # Kill any orphan process on the port (handles container restarts)
        if kill_process_on_port(port):
            log(f"Killed orphan process on port {port}")
        
        # Validate content
        validation = self.validate_content(content)
        log(f"Found {validation.file_count} files, {validation.deps_count} dependencies")
        
        if not validation.valid:
            for err in validation.errors:
                log(f"❌ {err}")
            return RunResult(
                success=False,
                port=port,
                message=validation.errors[0] if validation.errors else "Validation failed",
                logs=logs,
            )
        
        # Create temporary README file
        readme_path = self.sandbox_root / f"{service_name}_README.md"
        readme_path.write_text(content)
        
        # Create ServiceConfig
        service_env = {"PORT": str(port)}
        if env:
            service_env.update(env)
        
        service_config = ServiceConfig(
            name=service_name,
            readme=str(readme_path),
            port=port,
            env=service_env,
            health_check=self.default_health_check,
        )
        
        try:
            log(f"Creating sandbox for {service_name}")
            
            # Start service
            process = self.sandbox_manager.start_service(
                service=service_config,
                readme_path=readme_path,
                env=service_env,
                verbose=False,
                restart_if_running=False,  # Already handled above
            )
            
            log(f"Sandbox created: {process.sandbox_path}")
            log(f"Process started with PID: {process.pid}")
            
            # Wait for health check
            if wait_for_health:
                timeout = health_timeout or self.health_timeout
                log("Waiting for server to start...")
                
                health_result = await self._wait_for_health(
                    process=process,
                    port=port,
                    timeout=timeout,
                    on_log=log,
                )
                
                if not health_result:
                    # Cleanup
                    self.sandbox_manager.stop_service(service_name)
                    self.sandbox_manager.clean_sandbox(service_name)
                    log("❌ Server failed to start - check dependencies and code")
                    return RunResult(
                        success=False,
                        port=port,
                        message=f"Server failed to start within {timeout} seconds",
                        logs=logs,
                    )
            
            # Track mapping
            self._services[service_id] = service_name
            
            log(f"✓ Project running on http://localhost:{port}")
            log(f"  PID: {process.pid}")
            
            return RunResult(
                success=True,
                port=port,
                pid=process.pid,
                message=f"Service running on port {port}",
                logs=logs,
                service_name=service_name,
                sandbox_path=process.sandbox_path,
            )
            
        except Exception as e:
            log(f"Error starting service: {e}")
            return RunResult(
                success=False,
                port=port,
                message=f"Failed to start: {e}",
                logs=logs,
            )
    
    async def _wait_for_health(
        self,
        process: ServiceProcess,
        port: int,
        timeout: int,
        on_log: Callable[[str], None],
    ) -> bool:
        """Wait for service to pass health check."""
        attempts = timeout * 2  # Check every 0.5s
        
        for _ in range(attempts):
            await asyncio.sleep(0.5)
            
            # Check if process is still running
            if not process.is_running:
                exit_code = process.process.returncode if process.process else "unknown"
                on_log(f"❌ Process died (exit code: {exit_code})")
                
                # Try to get error output
                if process.process and process.process.stderr:
                    try:
                        stderr = process.process.stderr.read()
                        if stderr:
                            on_log(f"Error output: {stderr.decode()[:500]}")
                    except:
                        pass
                return False
            
            # Try to connect
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    resp = await client.get(f"http://localhost:{port}/")
                    if resp.status_code < 500:
                        on_log(f"✓ Server responding (status {resp.status_code})")
                        return True
            except:
                pass  # Keep trying
        
        return False
    
    def stop(self, service_id: str) -> RunResult:
        """Stop a running service."""
        logs: List[str] = []
        
        service_name = self._services.get(service_id)
        if not service_name:
            return RunResult(
                success=False,
                port=0,
                message="Service not found",
                logs=["No running service found with this ID"],
            )
        
        status = self.sandbox_manager.get_status(service_name)
        if not status:
            del self._services[service_id]
            return RunResult(
                success=False,
                port=0,
                message="Service not running",
                logs=["Service not found in sandbox manager"],
            )
        
        port = status.get("port", 0)
        logs.append(f"Stopping service on port {port}")
        
        try:
            success = self.sandbox_manager.stop_service(service_name)
            
            if success:
                logs.append("Process terminated")
                self.sandbox_manager.clean_sandbox(service_name)
                logs.append("Sandbox cleaned up")
                del self._services[service_id]
                
                return RunResult(
                    success=True,
                    port=port,
                    message="Service stopped",
                    logs=logs,
                )
            else:
                logs.append("Failed to stop service")
                return RunResult(
                    success=False,
                    port=port,
                    message="Failed to stop service",
                    logs=logs,
                )
        except Exception as e:
            logs.append(f"Error stopping service: {e}")
            return RunResult(
                success=False,
                port=port,
                message=f"Error: {e}",
                logs=logs,
            )
    
    def get_status(self, service_id: str) -> Optional[Dict]:
        """Get status of a service."""
        service_name = self._services.get(service_id)
        if not service_name:
            return None
        
        status = self.sandbox_manager.get_status(service_name)
        if not status:
            return None
        
        return {
            "service_id": service_id,
            "service_name": service_name,
            "running": status.get("running", False),
            "port": status.get("port"),
            "pid": status.get("pid"),
            "uptime": status.get("uptime"),
            "sandbox": status.get("sandbox"),
        }
    
    def list_services(self) -> List[Dict]:
        """List all running services."""
        result = []
        for service_id, service_name in self._services.items():
            status = self.sandbox_manager.get_status(service_name)
            if status:
                result.append({
                    "service_id": service_id,
                    "service_name": service_name,
                    "port": status.get("port"),
                    "pid": status.get("pid"),
                    "running": status.get("running", False),
                })
        return result
    
    async def test_endpoints(
        self,
        service_id: str,
        endpoints: Optional[List[str]] = None,
        timeout: float = 5.0,
    ) -> List[EndpointTestResult]:
        """Test endpoints of a running service."""
        if endpoints is None:
            endpoints = ["/", "/health", "/docs"]
        
        service_name = self._services.get(service_id)
        if not service_name:
            return [EndpointTestResult(
                endpoint="*",
                success=False,
                error="Service not found",
            )]
        
        status = self.sandbox_manager.get_status(service_name)
        if not status or not status.get("running"):
            return [EndpointTestResult(
                endpoint="*",
                success=False,
                error="Service not running",
            )]
        
        port = status.get("port")
        if not port:
            return [EndpointTestResult(
                endpoint="*",
                success=False,
                error="No port assigned",
            )]
        
        results = []
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            for endpoint in endpoints:
                url = f"http://localhost:{port}{endpoint}"
                start = time.time()
                
                try:
                    response = await client.get(url)
                    elapsed = (time.time() - start) * 1000
                    
                    results.append(EndpointTestResult(
                        endpoint=endpoint,
                        success=True,
                        status=response.status_code,
                        url=url,
                        response_time_ms=elapsed,
                    ))
                except Exception as e:
                    results.append(EndpointTestResult(
                        endpoint=endpoint,
                        success=False,
                        error=str(e),
                        url=url,
                    ))
        
        return results
    
    def stop_all(self) -> None:
        """Stop all running services."""
        for service_id in list(self._services.keys()):
            self.stop(service_id)
