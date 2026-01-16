"""
CQRS/Event Sourcing infrastructure for Pactown.

Provides a complete event sourcing foundation:
- Event: Immutable event records with versioning
- EventStore: Append-only event storage with subscriptions
- Aggregate: Base class for event-sourced aggregates
- Projections: Materialized views built from events
- Commands/Queries: CQRS pattern implementation

Usage:
    from pactown.events import (
        Event, EventType, EventStore, get_event_store,
        ServiceAggregate, ServiceCommands, ServiceQueries,
    )
    
    # Record events
    commands = ServiceCommands(get_event_store())
    await commands.create_service(service_id=1, user_id=1, name="api", port=8000)
    await commands.start_service(service_id=1, pid=12345)
    
    # Query events
    queries = ServiceQueries(get_event_store())
    history = queries.get_service_history(service_id=1)
    stats = queries.get_stats()
"""
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar
import asyncio
import json
import uuid


class EventType(str, Enum):
    """Standard event types for service lifecycle."""
    # Service lifecycle
    SERVICE_CREATED = "service.created"
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"
    SERVICE_DELETED = "service.deleted"
    SERVICE_HEALTH_CHECK = "service.health_check"
    SERVICE_ERROR = "service.error"
    SERVICE_RESTARTED = "service.restarted"
    
    # Sandbox lifecycle
    SANDBOX_CREATED = "sandbox.created"
    SANDBOX_DESTROYED = "sandbox.destroyed"
    SANDBOX_FILES_WRITTEN = "sandbox.files_written"
    SANDBOX_DEPS_INSTALLED = "sandbox.deps_installed"
    
    # Project lifecycle
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    PROJECT_VALIDATED = "project.validated"
    
    # User actions
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_CREATED = "user.created"
    
    # Security events
    SECURITY_CHECK_PASSED = "security.check_passed"
    SECURITY_CHECK_FAILED = "security.check_failed"
    RATE_LIMIT_HIT = "security.rate_limit"
    ANOMALY_DETECTED = "security.anomaly"
    
    # Deployment events
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_COMPLETED = "deployment.completed"
    DEPLOYMENT_FAILED = "deployment.failed"
    
    # Custom events
    CUSTOM = "custom"


@dataclass(frozen=True)
class Event:
    """
    Immutable event record.
    
    Events are the source of truth in event sourcing. Each event represents
    a fact that happened in the system at a specific point in time.
    
    Attributes:
        event_type: The type of event (from EventType enum or custom string)
        aggregate_id: ID of the aggregate this event belongs to (e.g., "service:123")
        aggregate_type: Type of aggregate (e.g., "service", "project", "user")
        data: Event payload with domain-specific data
        metadata: Additional context (user_id, correlation_id, etc.)
        timestamp: When the event occurred (UTC)
        event_id: Unique identifier for this event
        version: Event schema version for migrations
        sequence: Position in the event stream (set by EventStore)
    """
    event_type: EventType | str
    aggregate_id: str
    aggregate_type: str
    data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    sequence: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to dictionary for JSON storage."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "data": self.data,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "version": self.version,
            "sequence": self.sequence,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        """Deserialize event from dictionary."""
        event_type_str = d["event_type"]
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = event_type_str
        
        return cls(
            event_id=d["event_id"],
            event_type=event_type,
            aggregate_id=d["aggregate_id"],
            aggregate_type=d["aggregate_type"],
            data=d["data"],
            metadata=d.get("metadata", {}),
            timestamp=datetime.fromisoformat(d["timestamp"]) if isinstance(d["timestamp"], str) else d["timestamp"],
            version=d.get("version", 1),
            sequence=d.get("sequence", 0),
        )


class EventStore:
    """
    Append-only event store with subscription support.
    
    Provides:
    - Append-only event storage
    - Event subscriptions for reactive updates
    - Querying by aggregate, type, or time range
    - Optional persistence to JSON file
    
    Thread-safe for async operations.
    """
    
    def __init__(self, persistence_path: Optional[Path] = None):
        """
        Initialize event store.
        
        Args:
            persistence_path: Optional path to persist events to JSON file
        """
        self._events: List[Event] = []
        self._subscribers: Dict[EventType | str, List[Callable]] = defaultdict(list)
        self._global_subscribers: List[Callable] = []
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._persistence_path = persistence_path
        
        if persistence_path and persistence_path.exists():
            self._load_from_file()
    
    def _load_from_file(self) -> None:
        """Load events from persistence file."""
        try:
            with open(self._persistence_path, 'r') as f:
                data = json.load(f)
                self._events = [Event.from_dict(e) for e in data.get("events", [])]
                self._sequence = data.get("sequence", len(self._events))
        except (json.JSONDecodeError, KeyError):
            pass
    
    def _save_to_file(self) -> None:
        """Persist events to file."""
        if not self._persistence_path:
            return
        
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persistence_path, 'w') as f:
            json.dump({
                "events": [e.to_dict() for e in self._events],
                "sequence": self._sequence,
            }, f, indent=2, default=str)
    
    async def append(self, event: Event) -> Event:
        """
        Append event to store and notify subscribers.
        
        Args:
            event: Event to append
            
        Returns:
            Event with sequence number set
        """
        async with self._lock:
            self._sequence += 1
            # Create new event with sequence (Event is frozen)
            sequenced_event = Event(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                data=event.data,
                metadata=event.metadata,
                timestamp=event.timestamp,
                version=event.version,
                sequence=self._sequence,
            )
            self._events.append(sequenced_event)
            
            if self._persistence_path:
                self._save_to_file()
        
        # Notify subscribers asynchronously
        await self._notify_subscribers(sequenced_event)
        
        return sequenced_event
    
    async def _notify_subscribers(self, event: Event) -> None:
        """Notify all relevant subscribers of an event."""
        handlers = (
            self._subscribers.get(event.event_type, []) +
            self._global_subscribers
        )
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                print(f"Event handler error: {e}")
    
    def subscribe(self, event_type: EventType | str, handler: Callable) -> Callable[[], None]:
        """
        Subscribe to events of a specific type.
        
        Args:
            event_type: Type of events to subscribe to
            handler: Callback function (sync or async)
            
        Returns:
            Unsubscribe function
        """
        self._subscribers[event_type].append(handler)
        
        def unsubscribe():
            self._subscribers[event_type].remove(handler)
        
        return unsubscribe
    
    def subscribe_all(self, handler: Callable) -> Callable[[], None]:
        """
        Subscribe to all events.
        
        Args:
            handler: Callback function (sync or async)
            
        Returns:
            Unsubscribe function
        """
        self._global_subscribers.append(handler)
        
        def unsubscribe():
            self._global_subscribers.remove(handler)
        
        return unsubscribe
    
    def get_events(
        self,
        aggregate_id: Optional[str] = None,
        aggregate_type: Optional[str] = None,
        event_type: Optional[EventType | str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        since_sequence: Optional[int] = None,
        limit: int = 100,
    ) -> List[Event]:
        """
        Query events with filters.
        
        Args:
            aggregate_id: Filter by aggregate ID
            aggregate_type: Filter by aggregate type
            event_type: Filter by event type
            since: Filter events after this timestamp
            until: Filter events before this timestamp
            since_sequence: Filter events after this sequence number
            limit: Maximum number of events to return
            
        Returns:
            List of matching events
        """
        events = self._events
        
        if aggregate_id:
            events = [e for e in events if e.aggregate_id == aggregate_id]
        if aggregate_type:
            events = [e for e in events if e.aggregate_type == aggregate_type]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if since:
            events = [e for e in events if e.timestamp >= since]
        if until:
            events = [e for e in events if e.timestamp <= until]
        if since_sequence is not None:
            events = [e for e in events if e.sequence > since_sequence]
        
        return events[-limit:]
    
    def get_aggregate_history(self, aggregate_id: str) -> List[Event]:
        """Get all events for a specific aggregate in order."""
        return sorted(
            [e for e in self._events if e.aggregate_id == aggregate_id],
            key=lambda e: e.sequence
        )
    
    def count(self, event_type: Optional[EventType | str] = None) -> int:
        """Count events, optionally filtered by type."""
        if event_type:
            return len([e for e in self._events if e.event_type == event_type])
        return len(self._events)
    
    def get_current_sequence(self) -> int:
        """Get current sequence number."""
        return self._sequence
    
    def clear(self) -> None:
        """Clear all events (use with caution)."""
        self._events.clear()
        self._sequence = 0
        if self._persistence_path and self._persistence_path.exists():
            self._persistence_path.unlink()


# Global event store instance
_event_store: Optional[EventStore] = None


def get_event_store(persistence_path: Optional[Path] = None) -> EventStore:
    """Get or create global event store."""
    global _event_store
    if _event_store is None:
        _event_store = EventStore(persistence_path=persistence_path)
    return _event_store


def set_event_store(store: EventStore) -> None:
    """Set the global event store instance."""
    global _event_store
    _event_store = store


# Aggregate base class
T = TypeVar('T', bound='Aggregate')


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


# Command handlers (Write side of CQRS)
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


# Query handlers (Read side of CQRS)
class ServiceQueries:
    """
    Query handlers for service read operations.
    
    Queries don't modify state - they only read from the event store
    or materialized projections.
    """
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    def get_service_history(self, service_id: int) -> List[Dict]:
        """Get history of events for a service."""
        events = self.event_store.get_aggregate_history(f"service:{service_id}")
        return [e.to_dict() for e in events]
    
    def get_recent_starts(self, limit: int = 10) -> List[Dict]:
        """Get recent service starts."""
        events = self.event_store.get_events(
            event_type=EventType.SERVICE_STARTED,
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_recent_errors(self, limit: int = 10) -> List[Dict]:
        """Get recent service errors."""
        events = self.event_store.get_events(
            event_type=EventType.SERVICE_ERROR,
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_recent_health_checks(self, service_id: Optional[int] = None, limit: int = 10) -> List[Dict]:
        """Get recent health check results."""
        aggregate_id = f"service:{service_id}" if service_id else None
        events = self.event_store.get_events(
            aggregate_id=aggregate_id,
            event_type=EventType.SERVICE_HEALTH_CHECK,
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_stats(self) -> Dict[str, int]:
        """Get event statistics."""
        return {
            "total_events": self.event_store.count(),
            "services_created": self.event_store.count(EventType.SERVICE_CREATED),
            "services_started": self.event_store.count(EventType.SERVICE_STARTED),
            "services_stopped": self.event_store.count(EventType.SERVICE_STOPPED),
            "services_deleted": self.event_store.count(EventType.SERVICE_DELETED),
            "errors": self.event_store.count(EventType.SERVICE_ERROR),
            "health_checks": self.event_store.count(EventType.SERVICE_HEALTH_CHECK),
        }
    
    async def get_service_state(self, service_id: int) -> Dict[str, Any]:
        """Rebuild current service state from events."""
        aggregate = await ServiceAggregate.load(
            f"service:{service_id}",
            self.event_store
        )
        return aggregate.to_dict()
    
    def get_user_services(self, user_id: int) -> List[Dict]:
        """Get all service events for a user."""
        events = self.event_store.get_events(
            event_type=EventType.SERVICE_CREATED,
        )
        user_events = [e for e in events if e.data.get("user_id") == user_id]
        return [e.to_dict() for e in user_events]


class ProjectQueries:
    """Query handlers for project read operations."""
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    def get_project_history(self, project_id: int) -> List[Dict]:
        """Get history of events for a project."""
        events = self.event_store.get_aggregate_history(f"project:{project_id}")
        return [e.to_dict() for e in events]
    
    def get_recent_projects(self, user_id: Optional[int] = None, limit: int = 10) -> List[Dict]:
        """Get recently created projects."""
        events = self.event_store.get_events(
            event_type=EventType.PROJECT_CREATED,
            limit=limit,
        )
        if user_id:
            events = [e for e in events if e.data.get("user_id") == user_id]
        return [e.to_dict() for e in events]
    
    def get_stats(self) -> Dict[str, int]:
        """Get project statistics."""
        return {
            "projects_created": self.event_store.count(EventType.PROJECT_CREATED),
            "projects_updated": self.event_store.count(EventType.PROJECT_UPDATED),
            "projects_deleted": self.event_store.count(EventType.PROJECT_DELETED),
        }


class SecurityQueries:
    """Query handlers for security read operations."""
    
    def __init__(self, event_store: EventStore):
        self.event_store = event_store
    
    def get_recent_security_failures(self, limit: int = 10) -> List[Dict]:
        """Get recent security check failures."""
        events = self.event_store.get_events(
            event_type=EventType.SECURITY_CHECK_FAILED,
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_user_security_history(self, user_id: str, limit: int = 50) -> List[Dict]:
        """Get security event history for a user."""
        events = self.event_store.get_events(
            aggregate_id=f"user:{user_id}",
            aggregate_type="security",
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_rate_limit_hits(self, since: Optional[datetime] = None, limit: int = 100) -> List[Dict]:
        """Get recent rate limit hits."""
        events = self.event_store.get_events(
            event_type=EventType.RATE_LIMIT_HIT,
            since=since,
            limit=limit,
        )
        return [e.to_dict() for e in events]
    
    def get_anomalies(self, severity: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get security anomalies."""
        events = self.event_store.get_events(
            event_type=EventType.ANOMALY_DETECTED,
            limit=limit,
        )
        if severity:
            events = [e for e in events if e.data.get("severity") == severity]
        return [e.to_dict() for e in events]
    
    def get_stats(self) -> Dict[str, int]:
        """Get security statistics."""
        return {
            "security_checks_passed": self.event_store.count(EventType.SECURITY_CHECK_PASSED),
            "security_checks_failed": self.event_store.count(EventType.SECURITY_CHECK_FAILED),
            "rate_limit_hits": self.event_store.count(EventType.RATE_LIMIT_HIT),
            "anomalies_detected": self.event_store.count(EventType.ANOMALY_DETECTED),
        }


# Projections - Materialized views built from events
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


# Convenience functions for common patterns
def get_service_commands(event_store: Optional[EventStore] = None) -> ServiceCommands:
    """Get service command handlers."""
    return ServiceCommands(event_store or get_event_store())


def get_service_queries(event_store: Optional[EventStore] = None) -> ServiceQueries:
    """Get service query handlers."""
    return ServiceQueries(event_store or get_event_store())


def get_project_commands(event_store: Optional[EventStore] = None) -> ProjectCommands:
    """Get project command handlers."""
    return ProjectCommands(event_store or get_event_store())


def get_project_queries(event_store: Optional[EventStore] = None) -> ProjectQueries:
    """Get project query handlers."""
    return ProjectQueries(event_store or get_event_store())


def get_security_commands(event_store: Optional[EventStore] = None) -> SecurityCommands:
    """Get security command handlers."""
    return SecurityCommands(event_store or get_event_store())


def get_security_queries(event_store: Optional[EventStore] = None) -> SecurityQueries:
    """Get security query handlers."""
    return SecurityQueries(event_store or get_event_store())
