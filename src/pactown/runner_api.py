from __future__ import annotations

import logging
import os
import re
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .config import ServiceConfig
from .network import PortAllocator
from .platform import to_dns_label
from .security import UserProfile
from .service_runner import RunResult, ServiceRunner, ValidationResult

logger = logging.getLogger(__name__)


def _dns_label(value: str, fallback: str = "user") -> str:
    return to_dns_label(value, fallback=fallback)


def _validate_service_id(service_id: str) -> str:
    if not service_id:
        raise HTTPException(status_code=400, detail="service_id required")
    if "/" in service_id or "\\" in service_id:
        raise HTTPException(status_code=400, detail="invalid service_id")
    if ".." in service_id:
        raise HTTPException(status_code=400, detail="invalid service_id")
    return service_id


def _service_name_for(service_id: str) -> str:
    service_id = _validate_service_id(service_id)
    return f"service_{service_id}"


def _validate_rel_path(path: str) -> Path:
    if path is None:
        raise HTTPException(status_code=400, detail="path required")
    p = Path(str(path))
    if p.is_absolute():
        raise HTTPException(status_code=400, detail="path must be relative")
    if any(part in {"..", ""} for part in p.parts):
        raise HTTPException(status_code=400, detail="invalid path")
    return p


def _resolve_in_dir(root: Path, rel: Path) -> Path:
    root_r = root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root_r):
        raise HTTPException(status_code=400, detail="path escapes sandbox")
    return target


class UserProfileRequest(BaseModel):
    tier: str = "free"
    max_concurrent_services: int = 2
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_requests_per_minute: int = 30
    max_services_per_hour: int = 10


class RunRequest(BaseModel):
    project_id: int
    readme_content: str
    port: int = 0
    user_id: Optional[str] = None
    username: Optional[str] = None
    service_id: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    user_profile: Optional[UserProfileRequest] = None
    fast_mode: bool = False
    skip_health_check: bool = False


class StopRequest(BaseModel):
    project_id: int
    user_id: Optional[str] = None
    username: Optional[str] = None
    service_id: Optional[str] = None


class ValidateRequest(BaseModel):
    readme_content: str


class SandboxPrepareRequest(BaseModel):
    project_id: int
    readme_content: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    service_id: Optional[str] = None
    port: int = 0


class SandboxFileWriteRequest(BaseModel):
    content: str


class RunnerApiSettings:
    def __init__(self):
        import tempfile
        default_sandbox = tempfile.gettempdir() + "/pactown-sandboxes"
        self.sandbox_root = Path(os.environ.get("PACTOWN_SANDBOX_ROOT", default_sandbox))
        self.port_start = int(os.environ.get("PACTOWN_PORT_START", "10000"))
        self.port_end = int(os.environ.get("PACTOWN_PORT_END", "20000"))
        self.require_token = os.environ.get("PACTOWN_RUNNER_REQUIRE_TOKEN", "").lower() in {"1", "true", "yes"}
        self.token = os.environ.get("PACTOWN_RUNNER_TOKEN") or ""
        self.proxy_check_base_url = os.environ.get("PACTOWN_PROXY_CHECK_BASE_URL", "")
        self.domain = os.environ.get("PACTOWN_DOMAIN", "")


class RunnerService:
    def __init__(
        self,
        *,
        sandbox_root: Path,
        port_start: int,
        port_end: int,
        health_timeout: int = 30,
    ):
        self.settings = RunnerApiSettings()
        self.runner = ServiceRunner(sandbox_root=sandbox_root, default_health_check="/health", health_timeout=health_timeout)
        self.port_allocator = PortAllocator(start_port=port_start, end_port=port_end)

    def _resolve_service_id(self, req_service_id: Optional[str], project_id: int, username: Optional[str]) -> str:
        if req_service_id:
            return _validate_service_id(req_service_id)
        if username:
            return _validate_service_id(f"{int(project_id)}-{_dns_label(username, fallback=str(project_id))}")
        return _validate_service_id(str(int(project_id)))

    def validate(self, readme_content: str) -> ValidationResult:
        return self.runner.validate_content(readme_content)

    def _sandbox_path_for(self, service_id: str) -> Path:
        return self.runner.sandbox_manager.get_sandbox_path(_service_name_for(service_id))

    def list_sandbox_files(self, service_id: str) -> List[Dict[str, Any]]:
        sandbox_path = self._sandbox_path_for(service_id)
        if not sandbox_path.exists():
            raise HTTPException(status_code=404, detail="sandbox not found")

        files: List[Dict[str, Any]] = []
        for p in sandbox_path.rglob("*"):
            try:
                if p.is_dir():
                    continue
                rel = p.relative_to(sandbox_path)
                st = p.stat()
                files.append(
                    {
                        "path": str(rel),
                        "size": int(st.st_size),
                        "mtime": int(st.st_mtime),
                    }
                )
            except Exception:
                continue
        files.sort(key=lambda d: d.get("path", ""))
        return files

    def read_sandbox_file(self, service_id: str, path: str, limit: int = 200000) -> str:
        sandbox_path = self._sandbox_path_for(service_id)
        if not sandbox_path.exists():
            raise HTTPException(status_code=404, detail="sandbox not found")

        rel = _validate_rel_path(path)
        target = _resolve_in_dir(sandbox_path, rel)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")

        data = target.read_text(encoding="utf-8", errors="replace")
        if len(data) > limit:
            return data[:limit]
        return data

    def write_sandbox_file(self, service_id: str, path: str, content: str) -> None:
        sandbox_path = self._sandbox_path_for(service_id)
        sandbox_path.mkdir(parents=True, exist_ok=True)

        rel = _validate_rel_path(path)
        target = _resolve_in_dir(sandbox_path, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def delete_sandbox_file(self, service_id: str, path: str) -> None:
        sandbox_path = self._sandbox_path_for(service_id)
        if not sandbox_path.exists():
            raise HTTPException(status_code=404, detail="sandbox not found")

        rel = _validate_rel_path(path)
        target = _resolve_in_dir(sandbox_path, rel)
        if not target.exists():
            return
        if target.is_dir():
            raise HTTPException(status_code=400, detail="path is a directory")
        target.unlink()

    def prepare_sandbox(self, service_id: str, content: str, port: int = 0) -> Dict[str, Any]:
        validation = self.runner.validate_content(content)
        if not validation.valid:
            raise HTTPException(status_code=400, detail=validation.errors or ["validation failed"])

        service_name = _service_name_for(service_id)
        readme_path = self.runner.sandbox_root / f"{service_name}_README.md"
        readme_path.write_text(content)

        service_config = ServiceConfig(
            name=service_name,
            readme=str(readme_path),
            port=int(port) if port else 0,
            env={},
            health_check="/health",
        )

        logs: List[str] = []

        def on_log(msg: str) -> None:
            logs.append(msg)

        sandbox = self.runner.sandbox_manager.create_sandbox(
            service=service_config,
            readme_path=readme_path,
            install_dependencies=False,
            on_log=on_log,
        )

        return {
            "sandbox": str(sandbox.path),
            "files": self.list_sandbox_files(service_id),
            "logs": logs,
        }

    async def run(
        self,
        *,
        service_id: str,
        content: str,
        port: int,
        env: Optional[Dict[str, str]],
        user_id: Optional[str],
        username: Optional[str],
        user_profile: Optional[Dict[str, Any]],
        fast_mode: bool,
        skip_health_check: bool,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        effective_port = int(port)
        if effective_port <= 0:
            effective_port = self.port_allocator.allocate()
        else:
            effective_port = self.port_allocator.allocate(preferred_port=effective_port)

        if user_profile and user_id:
            profile = UserProfile.from_dict({**user_profile, "user_id": user_id})
            self.runner.security_policy.set_user_profile(profile)

        if fast_mode:
            result = await self.runner.fast_run(
                service_id=service_id,
                content=content,
                port=effective_port,
                env=env or {},
                user_id=user_id,
                user_profile=user_profile,
                skip_health_check=skip_health_check,
                on_log=on_log,
            )
        else:
            result = await self.runner.run_from_content(
                service_id=service_id,
                content=content,
                port=effective_port,
                env=env or {},
                restart_if_running=True,
                wait_for_health=not skip_health_check,
                user_id=user_id,
                user_profile=user_profile,
                on_log=on_log,
            )

        result.logs = result.logs or []

        base_url = self.settings.proxy_check_base_url
        domain = self.settings.domain
        if base_url and domain and (username or user_id):
            host = f"{service_id}.{domain}".lower()
            try:
                async with httpx.AsyncClient(follow_redirects=False, timeout=5.0) as client:
                    headers = {"host": host, "connection": "close"}
                    async with client.stream("GET", f"{base_url}/", headers=headers) as root_resp:
                        root_status = root_resp.status_code
                    async with client.stream("GET", f"{base_url}/health", headers=headers) as health_resp:
                        health_status = health_resp.status_code
                result.logs.extend(
                    [
                        f"[subdomain-check] host={host} / -> {root_status}",
                        f"[subdomain-check] host={host} /health -> {health_status}",
                    ]
                )
            except httpx.RemoteProtocolError as e:
                result.logs.append(
                    f"[subdomain-check][WARN] failed host={host}: RemoteProtocolError: {e}"
                )
            except Exception as e:
                result.logs.append(f"[subdomain-check][WARN] failed host={host}: {type(e).__name__}: {e}")

        return result


def create_runner_api(*, runner_service: RunnerService, settings: RunnerApiSettings) -> FastAPI:
    app = FastAPI(title="pactown-runner-api")

    def require_token(x_runner_token: Optional[str] = Header(default=None)) -> None:
        if not settings.require_token:
            return
        if not settings.token:
            raise HTTPException(status_code=500, detail="runner token not configured")
        if not x_runner_token or x_runner_token != settings.token:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True}

    @app.post("/validate", dependencies=[Depends(require_token)])
    async def validate(req: ValidateRequest) -> Dict[str, Any]:
        res = runner_service.validate(req.readme_content)
        return asdict(res)

    @app.post("/sandbox/prepare", dependencies=[Depends(require_token)])
    async def prepare_sandbox(req: SandboxPrepareRequest) -> Dict[str, Any]:
        service_id = runner_service._resolve_service_id(req.service_id, req.project_id, req.username)
        return runner_service.prepare_sandbox(service_id, req.readme_content, port=req.port)

    @app.get("/sandbox/{service_id}/files", dependencies=[Depends(require_token)])
    async def list_files(service_id: str) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        return {"files": runner_service.list_sandbox_files(service_id)}

    @app.get("/sandbox/{service_id}/file", dependencies=[Depends(require_token)])
    async def read_file(service_id: str, path: str) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        return {"path": path, "content": runner_service.read_sandbox_file(service_id, path)}

    @app.put("/sandbox/{service_id}/file", dependencies=[Depends(require_token)])
    async def write_file(service_id: str, path: str, body: SandboxFileWriteRequest) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        runner_service.write_sandbox_file(service_id, path, body.content)
        return {"ok": True}

    @app.delete("/sandbox/{service_id}/file", dependencies=[Depends(require_token)])
    async def delete_file(service_id: str, path: str) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        runner_service.delete_sandbox_file(service_id, path)
        return {"ok": True}

    @app.post("/run", dependencies=[Depends(require_token)])
    async def run(req: RunRequest) -> Dict[str, Any]:
        service_id = runner_service._resolve_service_id(req.service_id, req.project_id, req.username)
        user_profile_dict = req.user_profile.model_dump() if req.user_profile else None
        result = await runner_service.run(
            service_id=service_id,
            content=req.readme_content,
            port=req.port,
            env=req.env,
            user_id=req.user_id,
            username=req.username,
            user_profile=user_profile_dict,
            fast_mode=req.fast_mode,
            skip_health_check=req.skip_health_check,
        )
        return {
            "success": result.success,
            "port": result.port,
            "pid": result.pid,
            "message": result.message,
            "logs": result.logs or [],
            "error_category": result.error_category.value if hasattr(result.error_category, "value") else str(result.error_category),
            "stderr_output": result.stderr_output,
            "suggestions": [asdict(s) for s in (result.suggestions or [])],
            "diagnostics": asdict(result.diagnostics) if result.diagnostics else None,
            "service_name": result.service_name,
            "sandbox_path": str(result.sandbox_path) if getattr(result, "sandbox_path", None) else None,
            "user_id": req.user_id,
            "service_id": service_id,
        }

    @app.post("/run/stream", dependencies=[Depends(require_token)])
    async def run_stream(req: RunRequest) -> StreamingResponse:
        service_id = runner_service._resolve_service_id(req.service_id, req.project_id, req.username)
        user_profile_dict = req.user_profile.model_dump() if req.user_profile else None

        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_log(msg: str) -> None:
            try:
                loop.call_soon_threadsafe(q.put_nowait, {"type": "log", "message": msg})
            except Exception:
                pass

        async def run_job() -> None:
            try:
                def _run_in_thread() -> RunResult:
                    return asyncio.run(
                        runner_service.run(
                            service_id=service_id,
                            content=req.readme_content,
                            port=req.port,
                            env=req.env,
                            user_id=req.user_id,
                            username=req.username,
                            user_profile=user_profile_dict,
                            fast_mode=req.fast_mode,
                            skip_health_check=req.skip_health_check,
                            on_log=on_log,
                        )
                    )

                result = await asyncio.to_thread(_run_in_thread)
                payload = {
                    "success": result.success,
                    "port": result.port,
                    "pid": result.pid,
                    "message": result.message,
                    "logs": result.logs or [],
                    "error_category": result.error_category.value if hasattr(result.error_category, "value") else str(result.error_category),
                    "stderr_output": result.stderr_output,
                    "suggestions": [asdict(s) for s in (result.suggestions or [])],
                    "diagnostics": asdict(result.diagnostics) if result.diagnostics else None,
                    "service_name": result.service_name,
                    "sandbox_path": str(result.sandbox_path) if getattr(result, "sandbox_path", None) else None,
                    "user_id": req.user_id,
                    "service_id": service_id,
                }
                await q.put({"type": "result", "result": payload})
            except Exception as e:
                await q.put(
                    {
                        "type": "result",
                        "result": {
                            "success": False,
                            "port": int(req.port or 0),
                            "pid": None,
                            "message": f"Runner exception: {type(e).__name__}: {e}",
                            "logs": [],
                            "error_category": "exception",
                            "stderr_output": "",
                            "suggestions": [],
                            "diagnostics": None,
                            "service_name": None,
                            "sandbox_path": None,
                            "user_id": req.user_id,
                            "service_id": service_id,
                        },
                    }
                )
            finally:
                await q.put({"type": "eof"})

        task = asyncio.create_task(run_job())

        async def stream():
            try:
                while True:
                    item = await q.get()
                    if item.get("type") == "eof":
                        break
                    yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/test/{service_id}", dependencies=[Depends(require_token)])
    async def test_endpoints(service_id: str) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        results = await runner_service.runner.test_endpoints(service_id)
        return {
            "success": len(results) > 0 and results[0].endpoint != "*",
            "results": [asdict(r) for r in results],
        }

    @app.get("/cache/stats", dependencies=[Depends(require_token)])
    async def cache_stats() -> Dict[str, Any]:
        return runner_service.runner.get_cache_stats()

    @app.post("/stop", dependencies=[Depends(require_token)])
    async def stop(req: StopRequest) -> Dict[str, Any]:
        service_id = runner_service._resolve_service_id(req.service_id, req.project_id, req.username)
        status = runner_service.runner.get_status(service_id) or {}
        port = status.get("port")
        result = runner_service.runner.stop(service_id)
        if port:
            runner_service.port_allocator.release(int(port))
        return {
            "success": result.success,
            "port": result.port,
            "pid": result.pid,
            "message": result.message,
            "logs": result.logs or [],
            "error_category": result.error_category.value if hasattr(result.error_category, "value") else str(result.error_category),
            "stderr_output": result.stderr_output,
            "service_id": service_id,
        }

    @app.get("/status", dependencies=[Depends(require_token)])
    async def status(user_id: Optional[str] = None) -> Dict[str, Any]:
        services = runner_service.runner.list_services()
        if user_id:
            services = [s for s in services if s.get("user_id") == user_id]
        return {"services": services}

    @app.get("/status/{service_id}", dependencies=[Depends(require_token)])
    async def status_one(service_id: str) -> Dict[str, Any]:
        service_id = _validate_service_id(service_id)
        st = runner_service.runner.get_status(service_id)
        if not st:
            return {"running": False}
        return st

    return app


def create_app() -> FastAPI:
    settings = RunnerApiSettings()
    runner_service = RunnerService(
        sandbox_root=settings.sandbox_root,
        port_start=settings.port_start,
        port_end=settings.port_end,
    )
    return create_runner_api(runner_service=runner_service, settings=settings)


def main() -> None:
    import uvicorn

    app = create_app()
    host = os.environ.get("PACTOWN_RUNNER_HOST", "0.0.0.0")
    port = int(os.environ.get("PACTOWN_RUNNER_PORT", "8801"))
    uvicorn.run(app, host=host, port=port)
