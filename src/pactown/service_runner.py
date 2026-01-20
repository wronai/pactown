"""
High-level service runner for markpact projects.

Provides a simple API to run services directly from markdown content
with health checks, restart support, and endpoint testing.
"""

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from .config import CacheConfig, ServiceConfig
from .markpact_blocks import parse_blocks
from .sandbox_manager import SandboxManager, ServiceProcess, _write_dotenv_file


class ErrorCategory(str, Enum):
    """Categorized error types for better diagnostics."""
    NONE = "none"
    VALIDATION = "validation"  # Markpact content issues
    DEPENDENCY = "dependency"  # pip install failures
    PORT_CONFLICT = "port_conflict"  # Address already in use
    STARTUP_TIMEOUT = "startup_timeout"  # Server didn't respond in time
    PROCESS_CRASH = "process_crash"  # Process died unexpectedly
    ENVIRONMENT = "environment"  # Python/venv issues
    PERMISSION = "permission"  # File/directory access issues
    UNKNOWN = "unknown"


@dataclass
class DiagnosticInfo:
    """Environment diagnostics for debugging."""
    python_version: str = ""
    pip_version: str = ""
    disk_space_mb: int = 0
    sandbox_path: str = ""
    venv_exists: bool = False
    installed_packages: List[str] = field(default_factory=list)
    
    @classmethod
    def collect(cls, sandbox_path: Optional[Path] = None) -> "DiagnosticInfo":
        """Collect diagnostic information."""
        info = cls()
        
        # Python version
        info.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        
        # Pip version
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                info.pip_version = result.stdout.split()[1]
        except:
            pass
        
        # Disk space
        try:
            path = sandbox_path or Path("/tmp")
            stat = shutil.disk_usage(str(path))
            info.disk_space_mb = stat.free // (1024 * 1024)
        except:
            pass
        
        if sandbox_path:
            info.sandbox_path = str(sandbox_path)
            info.venv_exists = (sandbox_path / ".venv").exists()
        
        return info


@dataclass 
class AutoFixSuggestion:
    """Actionable suggestion to fix an error."""
    action: str  # e.g., "install_dependency", "change_port", "restart"
    description: str
    command: Optional[str] = None
    auto_fixable: bool = False


# Reserved/system ports that should never be killed by pactown
PROTECTED_PORTS = frozenset({
    22,    # SSH
    80,    # HTTP (Traefik, nginx, etc.)
    443,   # HTTPS (Traefik, nginx, etc.)
    5432,  # PostgreSQL
    6379,  # Redis
    3306,  # MySQL
    27017, # MongoDB
    8080,  # Common proxy port
    3000,  # Common dev server (Next.js, etc.)
})


def kill_process_on_port(port: int, force: bool = False) -> bool:
    """Kill any process using the specified port.
    
    Uses /proc filesystem to find processes (works in minimal containers).
    Returns True if a process was killed, False otherwise.
    
    Args:
        port: The port number to clear
        force: If True, bypass protected port check (use with caution)
        
    Note:
        Ports in PROTECTED_PORTS (80, 443, 22, etc.) are protected by default
        to prevent accidentally killing system services like Traefik.
    """
    # Safety check: don't kill processes on protected system ports
    if not force and port in PROTECTED_PORTS:
        return False
    
    # Additional safety: don't kill on ports below 1024 (privileged) unless forced
    if not force and port < 1024:
        return False
    
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


@dataclass
class RunResult:
    """Result of running a service with detailed diagnostics."""
    success: bool
    port: int
    pid: Optional[int] = None
    message: str = ""
    logs: List[str] = field(default_factory=list)
    service_name: Optional[str] = None
    sandbox_path: Optional[Path] = None
    # Enhanced error reporting
    error_category: ErrorCategory = ErrorCategory.NONE
    diagnostics: Optional[DiagnosticInfo] = None
    suggestions: List[AutoFixSuggestion] = field(default_factory=list)
    stderr_output: str = ""  # Captured stderr for debugging
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "port": self.port,
            "pid": self.pid,
            "message": self.message,
            "logs": self.logs,
            "service_name": self.service_name,
            "sandbox_path": str(self.sandbox_path) if self.sandbox_path else None,
            "error_category": self.error_category.value,
            "diagnostics": {
                "python_version": self.diagnostics.python_version,
                "pip_version": self.diagnostics.pip_version,
                "disk_space_mb": self.diagnostics.disk_space_mb,
                "sandbox_path": self.diagnostics.sandbox_path,
                "venv_exists": self.diagnostics.venv_exists,
            } if self.diagnostics else None,
            "suggestions": [
                {"action": s.action, "description": s.description, 
                 "command": s.command, "auto_fixable": s.auto_fixable}
                for s in self.suggestions
            ],
            "stderr_output": self.stderr_output,
        }


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
            port=8000,
            user_id="user123",  # Optional: for security policy enforcement
        )
        if result.success:
            print(f"Running on port {result.port}")
    """
    
    def __init__(
        self,
        sandbox_root: str | Path = None,  # Will use tempfile.gettempdir() if None
        default_health_check: str = "/health",
        health_timeout: int = 10,
        security_policy: Optional["SecurityPolicy"] = None,
        enable_fast_start: bool = True,
        cache_config: Optional[CacheConfig] = None,
    ):
        if sandbox_root is None:
            sandbox_root = os.environ.get("PACTOWN_SANDBOX_ROOT", tempfile.gettempdir() + "/pactown-sandboxes")
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.sandbox_manager = SandboxManager(self.sandbox_root)
        self.default_health_check = default_health_check
        self.health_timeout = health_timeout
        self._services: Dict[str, str] = {}  # external_id -> service_name
        self._service_users: Dict[str, str] = {}  # service_id -> user_id

        self.cache_config = cache_config or CacheConfig.from_env()
        self._cache_env: Dict[str, str] = self.cache_config.to_env()
        
        # Security policy - use provided or get global default
        from .security import get_security_policy
        self.security_policy = security_policy or get_security_policy()
        
        # Fast start - dependency caching for faster startup
        self.enable_fast_start = enable_fast_start
        if enable_fast_start:
            from .fast_start import FastServiceStarter
            self.fast_starter = FastServiceStarter(
                sandbox_root=self.sandbox_root,
                enable_caching=True,
                enable_pool=True,
            )
        else:
            self.fast_starter = None
    
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

    def _prune_stale_user_services(
        self,
        user_id: str,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        if not user_id or user_id == "anonymous":
            return

        for service_id, owner_id in list(self._service_users.items()):
            if owner_id != user_id:
                continue

            service_name = self._services.get(service_id)
            running = False
            if service_name:
                status = self.sandbox_manager.get_status(service_name)
                running = bool(status and status.get("running"))

            if running:
                continue

            if on_log:
                on_log(f"Pruning stale service: service_id={service_id} running={running}")

            try:
                self.security_policy.unregister_service(user_id, service_id)
            except Exception:
                pass

            if service_name:
                try:
                    self.sandbox_manager.stop_service(service_name)
                except Exception:
                    pass

            if service_id in self._services:
                del self._services[service_id]
            if service_id in self._service_users:
                del self._service_users[service_id]
    
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
        user_id: Optional[str] = None,
        user_profile: Optional[Dict[str, Any]] = None,
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
            user_id: User ID for security policy enforcement
            user_profile: User profile dict (tier, limits) for security checks
        
        Returns:
            RunResult with success status, logs, and service info
        """
        logs: List[str] = []
        service_name = f"service_{service_id}"
        effective_user_id = user_id or "anonymous"
        
        def log(msg: str):
            logs.append(msg)
            if on_log:
                on_log(msg)
        
        # Set user profile if provided
        if user_profile and user_id:
            from .security import UserProfile
            profile = UserProfile.from_dict({**user_profile, "user_id": user_id})
            self.security_policy.set_user_profile(profile)

        # Clean up stale services before enforcing concurrent limits
        self._prune_stale_user_services(effective_user_id, on_log=log)
        
        # Security check - can this user start a service?
        security_check = await self.security_policy.check_can_start_service(
            user_id=effective_user_id,
            service_id=service_id,
            port=port,
        )
        
        if not security_check.allowed:
            log(f"🔒 Security: {security_check.reason}")
            return RunResult(
                success=False,
                port=port,
                message=security_check.reason or "Security check failed",
                logs=logs,
                error_category=ErrorCategory.PERMISSION,
            )
        
        # Apply throttle delay if server is under load
        if security_check.delay_seconds > 0:
            log(f"⏳ Server under load, waiting {security_check.delay_seconds:.1f}s...")
            await asyncio.sleep(security_check.delay_seconds)
        
        # Check if already running (tracked by sandbox manager)
        status = self.sandbox_manager.get_status(service_name)
        if status and status.get("running"):
            if restart_if_running:
                log(f"Service {service_name} is running (PID: {status.get('pid')}), restarting...")
                try:
                    self.sandbox_manager.stop_service(service_name)
                    self.sandbox_manager.clean_sandbox(service_name)
                    # Wait for cleanup to complete
                    await asyncio.sleep(0.5)
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
        killed = kill_process_on_port(port)
        if killed:
            log(f"Killed orphan process on port {port}")
            await asyncio.sleep(0.3)  # Wait for port to be released
        
        # Validate content
        validation = self.validate_content(content)
        log(f"Found {validation.file_count} files, {validation.deps_count} dependencies")

        if validation.deps_count <= 0:
            eta_min_s, eta_max_s = 3, 12
        else:
            eta_min_s = 15
            eta_max_s = max(60, min(300, int(validation.deps_count) * 40))
        log(
            f"⏱️ Estimated startup time: ~{eta_min_s}-{eta_max_s}s "
            f"(deps={validation.deps_count}; first run may take longer; next runs may be faster)"
        )
        
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
        service_env: Dict[str, str] = {}
        if self._cache_env:
            service_env.update(self._cache_env)
        if env:
            service_env.update(env)
        service_env["PORT"] = str(port)
        
        service_config = ServiceConfig(
            name=service_name,
            readme=str(readme_path),
            port=port,
            env=service_env,
            health_check=self.default_health_check,
        )
        
        try:
            log(f"Creating sandbox for {service_name}")
            
            # Start service with detailed logging and user isolation
            process = self.sandbox_manager.start_service(
                service=service_config,
                readme_path=readme_path,
                env=service_env,
                verbose=False,
                restart_if_running=False,  # Already handled above
                on_log=log,  # Pass log callback for detailed logging
                user_id=effective_user_id if effective_user_id != "anonymous" else None,
            )
            
            # Check if process died immediately after startup
            if process.process and process.process.poll() is not None:
                exit_code = process.process.returncode
                stderr = ""
                if process.process.stderr:
                    try:
                        stderr = process.process.stderr.read().decode()[:1000]
                    except:
                        pass
                log(f"⚠️ Process exited immediately with code {exit_code}")
                if stderr:
                    log(f"STDERR: {stderr[:500]}")
            
            # Wait for health check
            if wait_for_health:
                timeout = health_timeout or self.health_timeout
                log("Waiting for server to start...")
                
                health_result = await self._wait_for_health(
                    process=process,
                    port=port,
                    timeout=timeout,
                    health_path=service_config.health_check or "/",
                    on_log=log,
                )
                
                if not health_result["success"]:
                    # Cleanup
                    self.sandbox_manager.stop_service(service_name)
                    self.sandbox_manager.clean_sandbox(service_name)
                    
                    error_cat = health_result.get("error_category", ErrorCategory.STARTUP_TIMEOUT)
                    stderr_out = health_result.get("stderr", "")
                    suggestions = self._generate_suggestions(error_cat, stderr_out, port)
                    
                    log("❌ Server failed to start - check dependencies and code")
                    return RunResult(
                        success=False,
                        port=port,
                        message=f"Server failed to start within {timeout} seconds",
                        logs=logs,
                        error_category=error_cat,
                        stderr_output=stderr_out,
                        suggestions=suggestions,
                        diagnostics=DiagnosticInfo.collect(process.sandbox_path),
                    )
            
            # Track mapping
            self._services[service_id] = service_name
            self._service_users[service_id] = effective_user_id
            
            # Register with security policy for concurrent service tracking
            self.security_policy.register_service(effective_user_id, service_id)
            
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
    
    def _generate_suggestions(
        self, 
        error_cat: ErrorCategory, 
        stderr: str,
        port: int
    ) -> List[AutoFixSuggestion]:
        """Generate actionable suggestions based on error type."""
        suggestions = []
        
        if error_cat == ErrorCategory.PORT_CONFLICT:
            suggestions.append(AutoFixSuggestion(
                action="kill_port_process",
                description=f"Kill process using port {port}",
                command=f"fuser -k {port}/tcp",
                auto_fixable=True,
            ))
            suggestions.append(AutoFixSuggestion(
                action="use_different_port",
                description="Try a different port",
            ))
        
        elif error_cat == ErrorCategory.DEPENDENCY:
            # Extract failed package from stderr
            if "No matching distribution" in stderr:
                pkg = stderr.split("No matching distribution found for")[-1].split()[0] if "for" in stderr else "unknown"
                suggestions.append(AutoFixSuggestion(
                    action="check_package_name",
                    description=f"Package '{pkg}' not found - check spelling or availability",
                ))
            suggestions.append(AutoFixSuggestion(
                action="clear_cache",
                description="Clear pip cache and retry",
                command="pip cache purge",
                auto_fixable=True,
            ))
        
        elif error_cat == ErrorCategory.PROCESS_CRASH:
            if "SyntaxError" in stderr:
                suggestions.append(AutoFixSuggestion(
                    action="fix_syntax",
                    description="Fix Python syntax error in code",
                ))
            if "ModuleNotFoundError" in stderr or "ImportError" in stderr or "No module named" in stderr:
                # Extract module name
                if "No module named" in stderr:
                    module = stderr.split("No module named")[-1].strip().split()[0].strip("'\"")
                    suggestions.append(AutoFixSuggestion(
                        action="add_dependency",
                        description=f"Add '{module}' to dependencies block",
                    ))
                else:
                    suggestions.append(AutoFixSuggestion(
                        action="check_imports",
                        description="Check that all imported modules are in dependencies",
                    ))
            if "Address already in use" in stderr:
                suggestions.append(AutoFixSuggestion(
                    action="kill_port_process",
                    description=f"Kill process using port {port}",
                    command=f"fuser -k {port}/tcp",
                    auto_fixable=True,
                ))
            if "Traceback" in stderr and not suggestions:
                # Generic crash - suggest checking logs
                suggestions.append(AutoFixSuggestion(
                    action="check_code",
                    description="Review code for runtime errors - see stderr_output for full traceback",
                ))
        
        elif error_cat == ErrorCategory.STARTUP_TIMEOUT:
            suggestions.append(AutoFixSuggestion(
                action="increase_timeout",
                description="Increase health check timeout for slow dependencies",
            ))
            suggestions.append(AutoFixSuggestion(
                action="check_run_command",
                description="Verify the run command starts a web server",
            ))
        
        return suggestions

    async def _wait_for_health(
        self,
        process: ServiceProcess,
        port: int,
        timeout: int,
        health_path: str,
        on_log: Callable[[str], None],
    ) -> dict:
        """Wait for service to pass health check.
        
        Returns dict with: success, error_category, stderr
        """
        attempts = timeout * 2  # Check every 0.5s
        stderr_output = ""

        started = time.monotonic()
        last_beat_s = -1
        try:
            beat_every_s = max(1, int(os.environ.get("PACTOWN_HEALTH_HEARTBEAT_S", "5")))
        except Exception:
            beat_every_s = 5

        health_path = (health_path or "/").strip()
        if not health_path.startswith("/"):
            health_path = "/" + health_path
        probe_paths = [health_path]
        if health_path != "/":
            probe_paths.append("/")

        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                for _ in range(attempts):
                    await asyncio.sleep(0.5)

                    elapsed_s = int(time.monotonic() - started)
                    if elapsed_s == 0 or (elapsed_s - last_beat_s) >= beat_every_s:
                        last_beat_s = elapsed_s
                        remaining = max(0, int(timeout) - elapsed_s)
                        on_log(f"⏳ [deploy] Waiting for server health... elapsed={elapsed_s}s remaining~{remaining}s")

                    # Check if process is still running
                    if not process.is_running:
                        exit_code = process.process.returncode if process.process else "unknown"
                        on_log(f"❌ Process died (exit code: {exit_code})")

                        # Try to get error output
                        if process.process and process.process.stderr:
                            try:
                                stderr_bytes = process.process.stderr.read()
                                if stderr_bytes:
                                    stderr_output = stderr_bytes.decode("utf-8", errors="replace")
                                    trimmed = stderr_output[:4000]
                                    on_log(f"Error output: {trimmed}")
                            except:
                                pass

                        # Categorize error based on stderr
                        error_cat = ErrorCategory.PROCESS_CRASH
                        if "Address already in use" in stderr_output:
                            error_cat = ErrorCategory.PORT_CONFLICT
                        elif "ModuleNotFoundError" in stderr_output or "No module named" in stderr_output:
                            error_cat = ErrorCategory.DEPENDENCY
                        elif "SyntaxError" in stderr_output:
                            error_cat = ErrorCategory.VALIDATION

                        return {"success": False, "error_category": error_cat, "stderr": stderr_output}

                    for path in probe_paths:
                        try:
                            resp = await client.get(f"http://localhost:{port}{path}")
                            if resp.status_code < 500 and not (path != "/" and resp.status_code == 404):
                                on_log(f"✓ Server responding on {path} (status {resp.status_code})")
                                return {"success": True, "error_category": ErrorCategory.NONE, "stderr": ""}
                        except:
                            pass
        except Exception:
            pass
        
        # Timeout reached - try to capture any stderr
        if process.is_running and process.process and process.process.stderr:
            try:
                import select
                if select.select([process.process.stderr], [], [], 0)[0]:
                    stderr_bytes = process.process.stderr.read(2000)
                    if stderr_bytes:
                        stderr_output = stderr_bytes.decode("utf-8", errors="replace")
                        on_log(f"Process output: {stderr_output[:500]}")
            except:
                pass
        on_log(f"⏱️ Health check timed out after {timeout}s - process still running: {process.is_running}")
        return {"success": False, "error_category": ErrorCategory.STARTUP_TIMEOUT, "stderr": stderr_output}
    
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
                
                # Unregister from security policy
                user_id = self._service_users.get(service_id, "anonymous")
                self.security_policy.unregister_service(user_id, service_id)
                if service_id in self._service_users:
                    del self._service_users[service_id]
                
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
            "user_id": self._service_users.get(service_id),
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
            if status and status.get("running"):
                result.append({
                    "service_id": service_id,
                    "service_name": service_name,
                    "user_id": self._service_users.get(service_id),
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
    
    async def fast_run(
        self,
        service_id: str,
        content: str,
        port: int,
        env: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        skip_health_check: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        """
        Fast service startup with dependency caching.
        
        Uses cached venvs to achieve millisecond startup for repeated deps.
        Security checks are still enforced.
        
        Args:
            service_id: Unique identifier
            content: Markdown content
            port: Port to run on
            env: Environment variables
            user_id: User ID for security
            user_profile: User profile for limits
            skip_health_check: Return immediately without waiting for health
            on_log: Log callback
        
        Returns:
            RunResult with startup time in message
        """
        import time as time_module
        start_time = time_module.time()
        logs: List[str] = []
        service_name = f"service_{service_id}"
        effective_user_id = user_id or "anonymous"

        effective_env: Dict[str, str] = {}
        if self._cache_env:
            effective_env.update(self._cache_env)
        if env:
            effective_env.update(env)
        
        def log(msg: str):
            logs.append(msg)
            if on_log:
                on_log(msg)
        
        # Security check (same as regular run)
        if user_profile and user_id:
            from .security import UserProfile
            profile = UserProfile.from_dict({**user_profile, "user_id": user_id})
            self.security_policy.set_user_profile(profile)

        # Clean up stale services before enforcing concurrent limits
        self._prune_stale_user_services(effective_user_id, on_log=log)
        
        security_check = await self.security_policy.check_can_start_service(
            user_id=effective_user_id,
            service_id=service_id,
            port=port,
        )
        
        if not security_check.allowed:
            log(f"🔒 Security: {security_check.reason}")
            return RunResult(
                success=False,
                port=port,
                message=security_check.reason or "Security check failed",
                logs=logs,
                error_category=ErrorCategory.PERMISSION,
            )
        
        # Apply throttle if needed
        if security_check.delay_seconds > 0:
            log(f"⏳ Throttle: {security_check.delay_seconds:.1f}s")
            await asyncio.sleep(security_check.delay_seconds)
        
        # Kill any orphan process on port
        if kill_process_on_port(port):
            log(f"Killed orphan on port {port}")
        
        # Use fast starter if available
        use_fast_starter = self.fast_starter is not None
        if use_fast_starter:
            try:
                probe_blocks = parse_blocks(content)
                probe_run = ""
                probe_deps: list[str] = []
                probe_node_deps: list[str] = []
                for b in probe_blocks:
                    if b.kind == "deps":
                        if getattr(self.sandbox_manager, "_is_node_lang", lambda _x: False)(getattr(b, "lang", "")):
                            probe_node_deps.extend(b.body.strip().split("\n"))
                        else:
                            probe_deps.extend(b.body.strip().split("\n"))
                    elif b.kind == "run":
                        probe_run = b.body.strip()

                is_node_project = getattr(self.sandbox_manager, "_infer_node_project", lambda **_k: False)(
                    blocks=probe_blocks,
                    deps=[d.strip() for d in (probe_node_deps or probe_deps) if str(d).strip()],
                    run_cmd=probe_run,
                )
                if is_node_project:
                    log("⚠️ Node.js project detected - disabling fast start")
                    use_fast_starter = False
            except Exception:
                pass

        if use_fast_starter and self.fast_starter:
            log("⚡ Fast start mode enabled")
            fast_result = await self.fast_starter.fast_create_sandbox(
                service_name=service_name,
                content=content,
                on_log=log,
                env=effective_env,
            )
            
            if not fast_result.success:
                return RunResult(
                    success=False,
                    port=port,
                    message=fast_result.message,
                    logs=logs,
                )
            
            sandbox_path = fast_result.sandbox_path
            cache_info = "cached" if fast_result.cache_hit else "fresh"
            log(f"⚡ Sandbox ready in {fast_result.startup_time_ms:.0f}ms ({cache_info})")
        else:
            # Fallback to regular sandbox creation
            log("Creating sandbox (no cache)...")
            validation = self.validate_content(content)
            if not validation.valid:
                return RunResult(
                    success=False,
                    port=port,
                    message=validation.errors[0] if validation.errors else "Validation failed",
                    logs=logs,
                )
            
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(content)
                readme_path = Path(f.name)

            # Use sandbox manager for regular creation
            config = ServiceConfig(name=service_name, readme=str(readme_path), port=port)
            
            try:
                sandbox = self.sandbox_manager.create_sandbox(config, readme_path, env=effective_env)
                sandbox_path = sandbox.path
            finally:
                readme_path.unlink()
        
        # Start the service process
        blocks = parse_blocks(content)
        run_cmd = None
        for block in blocks:
            if block.kind == "run":
                run_cmd = block.body.strip()
                break
        
        if not run_cmd:
            return RunResult(
                success=False,
                port=port,
                message="No run command found",
                logs=logs,
            )
        
        # Prepare environment
        run_env = os.environ.copy()
        run_env["PORT"] = str(port)
        run_env["HOST"] = "0.0.0.0"  # nosec B104: bind all interfaces for container/service access
        if effective_env:
            run_env.update(effective_env)

        dotenv_env = dict(effective_env or {})
        dotenv_env["PORT"] = str(port)
        dotenv_env["MARKPACT_PORT"] = str(port)
        _write_dotenv_file(sandbox_path, dotenv_env)
        
        # Resolve venv path (could be symlink to cache)
        venv_path = sandbox_path / ".venv"
        if venv_path.is_symlink():
            actual_venv = venv_path.resolve()
            run_env["VIRTUAL_ENV"] = str(actual_venv)
            run_env["PATH"] = f"{actual_venv}/bin:{run_env.get('PATH', '')}"
        elif venv_path.exists():
            run_env["VIRTUAL_ENV"] = str(venv_path)
            run_env["PATH"] = f"{venv_path}/bin:{run_env.get('PATH', '')}"
        
        # Expand $PORT in command
        run_cmd = run_cmd.replace("$PORT", str(port))
        
        log(f"Starting: {run_cmd[:50]}...")
        
        try:
            # nosec B602: shell=True required for user-defined run commands
            # Commands come from validated markpact README blocks
            process = subprocess.Popen(
                run_cmd,
                shell=True,  # nosec B602
                cwd=str(sandbox_path),
                env=run_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # Register service
            self._services[service_id] = service_name
            self._service_users[service_id] = effective_user_id
            self.security_policy.register_service(effective_user_id, service_id)
            
            # Track in sandbox manager
            from .sandbox_manager import ServiceProcess
            self.sandbox_manager._processes[service_name] = ServiceProcess(
                name=service_name,
                pid=process.pid,
                port=port,
                sandbox_path=sandbox_path,
                process=process,
            )
            
            total_time_ms = (time_module.time() - start_time) * 1000
            
            if skip_health_check:
                log(f"⚡ Started in {total_time_ms:.0f}ms (health check skipped)")
                return RunResult(
                    success=True,
                    port=port,
                    pid=process.pid,
                    message=f"Started in {total_time_ms:.0f}ms (async)",
                    logs=logs,
                    service_name=service_name,
                    sandbox_path=sandbox_path,
                )
            
            # Quick health check (max 5s for fast mode)
            log("Quick health check...")
            health_ok = await self._quick_health_check(
                process,
                port,
                timeout=5,
                health_path=self.default_health_check,
            )
            
            total_time_ms = (time_module.time() - start_time) * 1000
            
            if health_ok:
                log(f"✓ Running in {total_time_ms:.0f}ms")
                return RunResult(
                    success=True,
                    port=port,
                    pid=process.pid,
                    message=f"Running on port {port} ({total_time_ms:.0f}ms)",
                    logs=logs,
                    service_name=service_name,
                    sandbox_path=sandbox_path,
                )
            else:
                # Check if process died
                if process.poll() is not None:
                    stderr = process.stderr.read().decode()[:500] if process.stderr else ""
                    log(f"❌ Process died: {stderr[:200]}")
                    return RunResult(
                        success=False,
                        port=port,
                        message="Process crashed during startup",
                        logs=logs,
                        stderr_output=stderr,
                    )
                else:
                    log(f"⚠️ Health check timeout, but process running")
                    return RunResult(
                        success=True,
                        port=port,
                        pid=process.pid,
                        message=f"Started (health pending) in {total_time_ms:.0f}ms",
                        logs=logs,
                        service_name=service_name,
                        sandbox_path=sandbox_path,
                    )
                    
        except Exception as e:
            log(f"Error: {e}")
            return RunResult(
                success=False,
                port=port,
                message=str(e),
                logs=logs,
            )
    
    async def _quick_health_check(
        self,
        process: subprocess.Popen,
        port: int,
        timeout: int = 5,
        health_path: str = "/",
    ) -> bool:
        """Quick health check with shorter timeout."""
        health_path = (health_path or "/").strip()
        if not health_path.startswith("/"):
            health_path = "/" + health_path
        probe_paths = [health_path]
        if health_path != "/":
            probe_paths.append("/")

        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                for _ in range(timeout * 4):  # Check every 250ms
                    await asyncio.sleep(0.25)

                    if process.poll() is not None:
                        return False

                    for path in probe_paths:
                        try:
                            resp = await client.get(f"http://localhost:{port}{path}")
                            if resp.status_code < 500 and not (path != "/" and resp.status_code == 404):
                                return True
                        except:
                            pass
        except Exception:
            pass
        
        return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get fast start cache statistics."""
        if self.fast_starter:
            return self.fast_starter.get_cache_stats()
        return {"caching_enabled": False}
