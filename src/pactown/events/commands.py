"""CQRS command handlers."""
from typing import Any, Dict, List, Optional

from ..nfo_config import logged
from .store import EventStore
from .types import Event, EventType

class ServiceCommands:
    """
    Command handlers for service operations.
    
    Commands represent intentions to change state. Each command
    results in one or more events being recorded.
    """
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    async def create_service(
        self,
        service_id: int,
        user_id: int,
        name: str,
        port: int,
        **kwargs
    ) -> Event:
        """Record service creation."""
        event = Event(
            event_type=EventType.SERVICE_CREATED,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={
                "service_id": service_id,
                "user_id": user_id,
                "name": name,
                "port": port,
                **kwargs,
            },
            metadata={"user_id": user_id},
        )
        return await self.event_store.append(event)
    
    async def start_service(
        self,
        service_id: int,
        pid: Optional[int] = None,
        startup_time_ms: Optional[float] = None,
        cached: bool = False,
    ) -> Event:
        """Record service start."""
        event = Event(
            event_type=EventType.SERVICE_STARTED,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={
                "service_id": service_id,
                "pid": pid,
                "startup_time_ms": startup_time_ms,
                "cached": cached,
            },
        )
        return await self.event_store.append(event)
    
    async def stop_service(
        self,
        service_id: int,
        reason: str = "user_request",
    ) -> Event:
        """Record service stop."""
        event = Event(
            event_type=EventType.SERVICE_STOPPED,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={
                "service_id": service_id,
                "reason": reason,
            },
        )
        return await self.event_store.append(event)
    
    async def record_error(
        self,
        service_id: int,
        error: str,
        details: Optional[Dict] = None,
        fatal: bool = False,
    ) -> Event:
        """Record service error."""
        event = Event(
            event_type=EventType.SERVICE_ERROR,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={
                "service_id": service_id,
                "error": error,
                "details": details or {},
                "fatal": fatal,
            },
        )
        return await self.event_store.append(event)
    
    async def record_health_check(
        self,
        service_id: int,
        healthy: bool,
        response_time_ms: Optional[float] = None,
        status_code: Optional[int] = None,
    ) -> Event:
        """Record health check result."""
        event = Event(
            event_type=EventType.SERVICE_HEALTH_CHECK,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={
                "service_id": service_id,
                "healthy": healthy,
                "response_time_ms": response_time_ms,
                "status_code": status_code,
            },
        )
        return await self.event_store.append(event)
    
    async def delete_service(
        self,
        service_id: int,
        user_id: Optional[int] = None,
    ) -> Event:
        """Record service deletion."""
        event = Event(
            event_type=EventType.SERVICE_DELETED,
            aggregate_id=f"service:{service_id}",
            aggregate_type="service",
            data={"service_id": service_id},
            metadata={"user_id": user_id} if user_id else {},
        )
        return await self.event_store.append(event)


@logged
class ProjectCommands:
    """Command handlers for project operations."""
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    async def create_project(
        self,
        project_id: int,
        user_id: int,
        name: str,
        **kwargs
    ) -> Event:
        """Record project creation."""
        event = Event(
            event_type=EventType.PROJECT_CREATED,
            aggregate_id=f"project:{project_id}",
            aggregate_type="project",
            data={
                "project_id": project_id,
                "user_id": user_id,
                "name": name,
                **kwargs,
            },
            metadata={"user_id": user_id},
        )
        return await self.event_store.append(event)
    
    async def update_project(
        self,
        project_id: int,
        changes: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> Event:
        """Record project update."""
        event = Event(
            event_type=EventType.PROJECT_UPDATED,
            aggregate_id=f"project:{project_id}",
            aggregate_type="project",
            data={
                "project_id": project_id,
                "changes": changes,
            },
            metadata={"user_id": user_id} if user_id else {},
        )
        return await self.event_store.append(event)
    
    async def delete_project(
        self,
        project_id: int,
        user_id: Optional[int] = None,
    ) -> Event:
        """Record project deletion."""
        event = Event(
            event_type=EventType.PROJECT_DELETED,
            aggregate_id=f"project:{project_id}",
            aggregate_type="project",
            data={"project_id": project_id},
            metadata={"user_id": user_id} if user_id else {},
        )
        return await self.event_store.append(event)


@logged
class SecurityCommands:
    """Command handlers for security events."""
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    async def record_security_check(
        self,
        user_id: str,
        service_id: str,
        passed: bool,
        reason: Optional[str] = None,
        details: Optional[Dict] = None,
    ) -> Event:
        """Record security check result."""
        event_type = EventType.SECURITY_CHECK_PASSED if passed else EventType.SECURITY_CHECK_FAILED
        event = Event(
            event_type=event_type,
            aggregate_id=f"user:{user_id}",
            aggregate_type="security",
            data={
                "user_id": user_id,
                "service_id": service_id,
                "passed": passed,
                "reason": reason,
                "details": details or {},
            },
        )
        return await self.event_store.append(event)
    
    async def record_rate_limit(
        self,
        user_id: str,
        endpoint: str,
        limit: int,
    ) -> Event:
        """Record rate limit hit."""
        event = Event(
            event_type=EventType.RATE_LIMIT_HIT,
            aggregate_id=f"user:{user_id}",
            aggregate_type="security",
            data={
                "user_id": user_id,
                "endpoint": endpoint,
                "limit": limit,
            },
        )
        return await self.event_store.append(event)
    
    async def record_anomaly(
        self,
        user_id: str,
        anomaly_type: str,
        severity: str,
        details: Optional[Dict] = None,
    ) -> Event:
        """Record security anomaly."""
        event = Event(
            event_type=EventType.ANOMALY_DETECTED,
            aggregate_id=f"user:{user_id}",
            aggregate_type="security",
            data={
                "user_id": user_id,
                "anomaly_type": anomaly_type,
                "severity": severity,
                "details": details or {},
            },
        )
        return await self.event_store.append(event)
