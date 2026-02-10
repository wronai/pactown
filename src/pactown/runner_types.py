"""Standalone data types and helpers used by the service runner.

Extracted from service_runner.py to keep the ServiceRunner class
focused on orchestration logic.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


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
        except Exception:
            pass
        
        # Disk space
        try:
            path = sandbox_path or Path("/tmp")
            stat = shutil.disk_usage(str(path))
            info.disk_space_mb = stat.free // (1024 * 1024)
        except Exception:
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
    error_context: Optional[Dict[str, Any]] = None
    error_report_md: Optional[str] = None
    
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
            "error_context": self.error_context,
            "error_report_md": self.error_report_md,
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
