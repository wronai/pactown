"""Event-sourced aggregates."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar

from .store import EventStore
from .types import Event, EventType

T = TypeVar("T", bound="Aggregate")


class Aggregate(ABC):
    """
    Base class for event-sourced aggregates.
    
    Aggregates encapsulate domain logic and maintain consistency boundaries.
    State is rebuilt by replaying events.
    
    Usage:
        class ServiceAggregate(Aggregate):
            def __init__(self, aggregate_id: str):
                super().__init__(aggregate_id, "service")
                self.name = ""
                self.status = "pending"
            
            def apply_event(self, event: Event) -> None:
                if event.event_type == EventType.SERVICE_CREATED:
                    self.name = event.data["name"]
                    self.status = "created"
                elif event.event_type == EventType.SERVICE_STARTED:
                    self.status = "running"
    """
    
    def __init__(self, aggregate_id: str, aggregate_type: str):
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        self.version = 0
        self._pending_events: List[Event] = []
    
    @abstractmethod
    def apply_event(self, event: Event) -> None:
        """Apply an event to update aggregate state."""
        pass
    
    def load_from_history(self, events: List[Event]) -> None:
        """Rebuild state from event history."""
        for event in events:
            self.apply_event(event)
            self.version = event.sequence
    
    def raise_event(self, event_type: EventType | str, data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Event:
        """
        Raise a new event from this aggregate.
        
        Args:
            event_type: Type of event
            data: Event payload
            metadata: Optional metadata
            
        Returns:
            The raised event (not yet persisted)
        """
        event = Event(
            event_type=event_type,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            data=data,
            metadata=metadata or {},
        )
        self._pending_events.append(event)
        self.apply_event(event)
        return event
    
    def get_pending_events(self) -> List[Event]:
        """Get events raised but not yet persisted."""
        return self._pending_events.copy()
    
    def clear_pending_events(self) -> None:
        """Clear pending events after persistence."""
        self._pending_events.clear()
    
    @classmethod
    async def load(cls: type[T], aggregate_id: str, event_store: EventStore) -> T:
        """Load aggregate from event store."""
        instance = cls(aggregate_id)
        events = event_store.get_aggregate_history(aggregate_id)
        instance.load_from_history(events)
        return instance


class ServiceAggregate(Aggregate):
    """
    Event-sourced aggregate for service lifecycle.
    
    Tracks service state through events, enabling:
    - Full audit trail of service changes
    - State reconstruction at any point in time
    - Eventual consistency with read models
    """
    
    def __init__(self, aggregate_id: str):
        super().__init__(aggregate_id, "service")
        self.service_id: Optional[int] = None
        self.user_id: Optional[int] = None
        self.name: str = ""
        self.port: int = 0
        self.status: str = "pending"
        self.pid: Optional[int] = None
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.error_count: int = 0
        self.last_error: Optional[str] = None
    
    def apply_event(self, event: Event) -> None:
        """Apply event to update service state."""
        if event.event_type == EventType.SERVICE_CREATED:
            self.service_id = event.data.get("service_id")
            self.user_id = event.data.get("user_id")
            self.name = event.data.get("name", "")
            self.port = event.data.get("port", 0)
            self.status = "created"
            
        elif event.event_type == EventType.SERVICE_STARTED:
            self.status = "running"
            self.pid = event.data.get("pid")
            self.started_at = event.timestamp
            
        elif event.event_type == EventType.SERVICE_STOPPED:
            self.status = "stopped"
            self.pid = None
            self.stopped_at = event.timestamp
            
        elif event.event_type == EventType.SERVICE_ERROR:
            self.error_count += 1
            self.last_error = event.data.get("error")
            if event.data.get("fatal", False):
                self.status = "error"
                
        elif event.event_type == EventType.SERVICE_DELETED:
            self.status = "deleted"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize aggregate state."""
        return {
            "aggregate_id": self.aggregate_id,
            "service_id": self.service_id,
            "user_id": self.user_id,
            "name": self.name,
            "port": self.port,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "version": self.version,
        }
