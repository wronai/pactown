"""Event projections."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .store import EventStore
from .types import Event, EventType

class Projection(ABC):
    """
    Base class for event projections.
    
    Projections maintain materialized views that are optimized for
    specific query patterns. They're rebuilt by replaying events.
    """
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
        self._last_sequence = 0
    
    @abstractmethod
    def apply(self, event: Event) -> None:
        """Apply an event to update the projection."""
        pass
    
    def rebuild(self) -> None:
        """Rebuild projection from all events."""
        self._last_sequence = 0
        for event in self.event_store.get_events(limit=10000):
            self.apply(event)
            self._last_sequence = event.sequence
    
    def catch_up(self) -> None:
        """Apply new events since last update."""
        events = self.event_store.get_events(
            since_sequence=self._last_sequence,
            limit=1000,
        )
        for event in events:
            self.apply(event)
            self._last_sequence = event.sequence


class ServiceStatusProjection(Projection):
    """
    Projection maintaining current status of all services.
    
    Optimized for queries like "list all running services".
    """
    
    def __init__(self, event_store: EventStore):
        super().__init__(event_store)
        self._services: Dict[str, Dict[str, Any]] = {}
    
    def apply(self, event: Event) -> None:
        """Update service status based on event."""
        if event.aggregate_type != "service":
            return
        
        service_id = event.aggregate_id
        
        if event.event_type == EventType.SERVICE_CREATED:
            self._services[service_id] = {
                "service_id": event.data.get("service_id"),
                "user_id": event.data.get("user_id"),
                "name": event.data.get("name"),
                "port": event.data.get("port"),
                "status": "created",
                "created_at": event.timestamp.isoformat(),
            }
        elif event.event_type == EventType.SERVICE_STARTED:
            if service_id in self._services:
                self._services[service_id]["status"] = "running"
                self._services[service_id]["pid"] = event.data.get("pid")
                self._services[service_id]["started_at"] = event.timestamp.isoformat()
        elif event.event_type == EventType.SERVICE_STOPPED:
            if service_id in self._services:
                self._services[service_id]["status"] = "stopped"
                self._services[service_id]["pid"] = None
        elif event.event_type == EventType.SERVICE_DELETED:
            self._services.pop(service_id, None)
        elif event.event_type == EventType.SERVICE_ERROR:
            if service_id in self._services:
                self._services[service_id]["last_error"] = event.data.get("error")
                if event.data.get("fatal"):
                    self._services[service_id]["status"] = "error"
    
    def get_all(self) -> List[Dict[str, Any]]:
        """Get all services."""
        return list(self._services.values())
    
    def get_running(self) -> List[Dict[str, Any]]:
        """Get only running services."""
        return [s for s in self._services.values() if s.get("status") == "running"]
    
    def get_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Get services for a specific user."""
        return [s for s in self._services.values() if s.get("user_id") == user_id]
    
    def get(self, service_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific service."""
        return self._services.get(service_id)


