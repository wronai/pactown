"""Sandbox manager for pactown services."""

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from threading import Lock
from typing import Callable, Optional, List, Dict, Any

from markpact import Sandbox, ensure_venv
from markpact.runner import install_deps

from .config import ServiceConfig
from .markpact_blocks import parse_blocks

# Configure detailed logging
logger = logging.getLogger("pactown.sandbox")
logger.setLevel(logging.DEBUG)

# File handler for persistent logs
LOG_DIR = Path("/tmp/pactown-logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(LOG_DIR / "sandbox.log")
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
))
logger.addHandler(file_handler)


@dataclass
class ServiceProcess:
    """Represents a running service process."""
    name: str
    pid: int
    port: Optional[int]
    sandbox_path: Path
    process: Optional[subprocess.Popen] = None
    started_at: float = field(default_factory=time.time)

    @property
    def is_running(self) -> bool:
        if self.process:
            return self.process.poll() is None
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False


class SandboxManager:
    """Manages sandboxes for multiple services."""

    def __init__(self, sandbox_root: str | Path):
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, ServiceProcess] = {}

    def get_sandbox_path(self, service_name: str) -> Path:
        """Get sandbox path for a service."""
        return self.sandbox_root / service_name

    def create_sandbox(
        self,
        service: ServiceConfig,
        readme_path: Path,
        install_dependencies: bool = True,
    ) -> Sandbox:
        """Create a sandbox for a service from its README."""
        sandbox_path = self.get_sandbox_path(service.name)

        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)
        sandbox_path.mkdir(parents=True)

        sandbox = Sandbox(sandbox_path)

        readme_content = readme_path.read_text()
        blocks = parse_blocks(readme_content)

        deps: list[str] = []

        for block in blocks:
            if block.kind == "deps":
                deps.extend(block.body.strip().split("\n"))
            elif block.kind == "file":
                file_path = block.get_path() or "main.py"
                sandbox.write_file(file_path, block.body)
            elif block.kind == "run":
                block.body.strip()

        deps_clean = [d.strip() for d in deps if d.strip()]
        if deps_clean:
            # Always write requirements.txt so the sandbox can be used as a container build context
            sandbox.write_requirements(deps_clean)

            if install_dependencies:
                ensure_venv(sandbox, verbose=False)
                install_deps(deps_clean, sandbox, verbose=False)

        return sandbox

    def start_service(
        self,
        service: ServiceConfig,
        readme_path: Path,
        env: dict[str, str],
        verbose: bool = True,
        restart_if_running: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> ServiceProcess:
        """Start a service in its sandbox.
        
        Args:
            service: Service configuration
            readme_path: Path to README.md with markpact blocks
            env: Environment variables to pass to the service
            verbose: Print status messages
            restart_if_running: If True, stop and restart if already running
            on_log: Callback for detailed logging
        """
        def log(msg: str, level: str = "INFO"):
            logger.log(getattr(logging, level), f"[{service.name}] {msg}")
            if on_log:
                on_log(msg)
            if verbose:
                print(msg)
        
        log(f"Starting service: {service.name}", "INFO")
        log(f"Port: {service.port}, README: {readme_path}", "DEBUG")
        
        if service.name in self._processes:
            existing = self._processes[service.name]
            if existing.is_running:
                if restart_if_running:
                    log(f"Restarting {service.name}...", "INFO")
                    self.stop_service(service.name)
                    self.clean_sandbox(service.name)
                else:
                    log(f"Service {service.name} already running", "ERROR")
                    raise RuntimeError(f"Service {service.name} is already running")

        # Create sandbox with dependency installation
        log("Creating sandbox and installing dependencies...", "INFO")
        try:
            sandbox = self.create_sandbox(service, readme_path, install_dependencies=True)
            log(f"Sandbox created at: {sandbox.path}", "INFO")
        except Exception as e:
            log(f"Failed to create sandbox: {e}", "ERROR")
            logger.exception(f"Sandbox creation failed for {service.name}")
            raise

        readme_content = readme_path.read_text()
        blocks = parse_blocks(readme_content)

        run_command = None
        for block in blocks:
            if block.kind == "run":
                run_command = block.body.strip()
                break

        if not run_command:
            log(f"No run command found in README", "ERROR")
            raise ValueError(f"No run command found in {readme_path}")

        log(f"Run command: {run_command}", "DEBUG")

        full_env = os.environ.copy()
        full_env.update(env)

        if sandbox.has_venv():
            venv_bin = str(sandbox.venv_bin)
            full_env["PATH"] = f"{venv_bin}:{full_env.get('PATH', '')}"
            full_env["VIRTUAL_ENV"] = str(sandbox.path / ".venv")
            log(f"Using venv: {sandbox.path / '.venv'}", "DEBUG")
        else:
            log("WARNING: No venv found, using system Python", "WARNING")

        # Expand $PORT in command
        expanded_cmd = run_command.replace("$PORT", str(service.port))
        log(f"Expanded command: {expanded_cmd}", "DEBUG")

        log(f"Starting process...", "INFO")

        # Always capture stderr for debugging
        process = subprocess.Popen(
            expanded_cmd,
            shell=True,
            cwd=str(sandbox.path),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        log(f"Process started with PID: {process.pid}", "INFO")

        # Log initial stderr output after short delay
        time.sleep(0.5)
        if process.poll() is not None:
            # Process already died
            exit_code = process.returncode
            stderr = process.stderr.read().decode() if process.stderr else ""
            stdout = process.stdout.read().decode() if process.stdout else ""
            log(f"Process died immediately with exit code: {exit_code}", "ERROR")
            log(f"STDERR: {stderr[:1000]}", "ERROR")
            if stdout:
                log(f"STDOUT: {stdout[:500]}", "DEBUG")
            
            # Write to error log file
            error_log = LOG_DIR / f"{service.name}_error.log"
            with open(error_log, "w") as f:
                f.write(f"Exit code: {exit_code}\n")
                f.write(f"Command: {expanded_cmd}\n")
                f.write(f"CWD: {sandbox.path}\n")
                f.write(f"\n--- STDERR ---\n{stderr}\n")
                f.write(f"\n--- STDOUT ---\n{stdout}\n")
            log(f"Error log written to: {error_log}", "DEBUG")

        svc_process = ServiceProcess(
            name=service.name,
            pid=process.pid,
            port=service.port,
            sandbox_path=sandbox.path,
            process=process,
        )

        self._processes[service.name] = svc_process
        
        # Log sandbox contents for debugging
        try:
            files = list(sandbox.path.glob("*"))
            log(f"Sandbox files: {[f.name for f in files]}", "DEBUG")
        except:
            pass
        
        return svc_process

    def stop_service(self, service_name: str, timeout: int = 10) -> bool:
        """Stop a running service."""
        if service_name not in self._processes:
            return False

        svc = self._processes[service_name]

        if not svc.is_running:
            del self._processes[service_name]
            return True

        try:
            os.killpg(os.getpgid(svc.pid), signal.SIGTERM)
        except ProcessLookupError:
            del self._processes[service_name]
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not svc.is_running:
                break
            time.sleep(0.1)

        if svc.is_running:
            try:
                os.killpg(os.getpgid(svc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

        del self._processes[service_name]
        return True

    def stop_all(self, timeout: int = 10) -> None:
        """Stop all running services."""
        for name in list(self._processes.keys()):
            self.stop_service(name, timeout)

    def get_status(self, service_name: str) -> Optional[dict]:
        """Get status of a service."""
        if service_name not in self._processes:
            return None

        svc = self._processes[service_name]
        return {
            "name": svc.name,
            "pid": svc.pid,
            "port": svc.port,
            "running": svc.is_running,
            "uptime": time.time() - svc.started_at,
            "sandbox": str(svc.sandbox_path),
        }

    def get_all_status(self) -> list[dict]:
        """Get status of all services."""
        return [
            self.get_status(name)
            for name in self._processes
            if self.get_status(name)
        ]

    def clean_sandbox(self, service_name: str) -> None:
        """Remove sandbox directory for a service."""
        sandbox_path = self.get_sandbox_path(service_name)
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

    def clean_all(self) -> None:
        """Remove all sandbox directories."""
        if self.sandbox_root.exists():
            shutil.rmtree(self.sandbox_root)
        self.sandbox_root.mkdir(parents=True)

    def create_sandboxes_parallel(
        self,
        services: list[tuple[ServiceConfig, Path]],
        max_workers: int = 4,
        on_complete: Optional[Callable[[str, bool, float], None]] = None,
    ) -> dict[str, Sandbox]:
        """
        Create sandboxes for multiple services in parallel.

        Args:
            services: List of (ServiceConfig, readme_path) tuples
            max_workers: Maximum parallel workers
            on_complete: Callback(name, success, duration)

        Returns:
            Dict of {service_name: Sandbox}
        """
        results: dict[str, Sandbox] = {}
        errors: dict[str, str] = {}
        lock = Lock()

        def create_one(service: ServiceConfig, readme_path: Path) -> tuple[str, Sandbox]:
            sandbox = self.create_sandbox(service, readme_path)
            return service.name, sandbox

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            start_times = {}

            for service, readme_path in services:
                start_times[service.name] = time.time()
                future = executor.submit(create_one, service, readme_path)
                futures[future] = service.name

            for future in as_completed(futures):
                name = futures[future]
                duration = time.time() - start_times[name]

                try:
                    _, sandbox = future.result()
                    with lock:
                        results[name] = sandbox
                    if on_complete:
                        on_complete(name, True, duration)
                except Exception as e:
                    with lock:
                        errors[name] = str(e)
                    if on_complete:
                        on_complete(name, False, duration)

        if errors:
            error_msg = "; ".join(f"{k}: {v}" for k, v in errors.items())
            raise RuntimeError(f"Failed to create sandboxes: {error_msg}")

        return results

    def start_services_parallel(
        self,
        services: list[tuple[ServiceConfig, Path, dict[str, str]]],
        max_workers: int = 4,
        on_complete: Optional[Callable[[str, bool, float], None]] = None,
    ) -> dict[str, ServiceProcess]:
        """
        Start multiple services in parallel.

        Note: Should only be used for services with no inter-dependencies.
        For dependent services, use the orchestrator's wave-based approach.

        Args:
            services: List of (ServiceConfig, readme_path, env) tuples
            max_workers: Maximum parallel workers
            on_complete: Callback(name, success, duration)

        Returns:
            Dict of {service_name: ServiceProcess}
        """
        results: dict[str, ServiceProcess] = {}
        errors: dict[str, str] = {}
        lock = Lock()

        def start_one(
            service: ServiceConfig,
            readme_path: Path,
            env: dict[str, str]
        ) -> tuple[str, ServiceProcess]:
            proc = self.start_service(service, readme_path, env, verbose=False)
            return service.name, proc

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            start_times = {}

            for service, readme_path, env in services:
                start_times[service.name] = time.time()
                future = executor.submit(start_one, service, readme_path, env)
                futures[future] = service.name

            for future in as_completed(futures):
                name = futures[future]
                duration = time.time() - start_times[name]

                try:
                    _, proc = future.result()
                    with lock:
                        results[name] = proc
                    if on_complete:
                        on_complete(name, True, duration)
                except Exception as e:
                    with lock:
                        errors[name] = str(e)
                    if on_complete:
                        on_complete(name, False, duration)

        return results, errors
