"""Parallel multi-service fast startup."""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..nfo_config import logged
from .starter import FastServiceStarter
from .types import FastStartResult

@logged
class ParallelServiceRunner:
    """
    Run multiple services in parallel with optimized startup.
    """
    
    def __init__(self, fast_starter: FastServiceStarter, max_parallel: int = 4):
        self.fast_starter = fast_starter
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
    
    async def run_parallel(
        self,
        services: List[Dict[str, Any]],
        on_service_log: Optional[Callable[[str, str], None]] = None,
    ) -> List[FastStartResult]:
        """
        Run multiple services in parallel.
        
        Args:
            services: List of dicts with {service_id, content, port}
            on_service_log: Callback (service_id, message)
        
        Returns:
            List of FastStartResult for each service
        """
        async def run_one(svc: Dict[str, Any]) -> FastStartResult:
            async with self._semaphore:
                service_id = svc["service_id"]
                
                def log(msg: str):
                    if on_service_log:
                        on_service_log(service_id, msg)
                
                return await self.fast_starter.fast_create_sandbox(
                    service_name=f"service_{service_id}",
                    content=svc["content"],
                    on_log=log,
                )
        
        results = await asyncio.gather(*[run_one(s) for s in services])
        return list(results)


# Global fast starter instance
_fast_starter: Optional[FastServiceStarter] = None


def get_fast_starter(sandbox_root: Optional[Path] = None) -> FastServiceStarter:
    """Get or create the global fast starter instance."""
    global _fast_starter
    if _fast_starter is None:
        import tempfile
        root = sandbox_root or Path(os.environ.get("PACTOWN_SANDBOX_ROOT", tempfile.gettempdir() + "/pactown-sandboxes"))
        _fast_starter = FastServiceStarter(root)
    return _fast_starter
