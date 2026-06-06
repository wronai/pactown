"""Event types and records."""
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Dict
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

