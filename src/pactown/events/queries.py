"""CQRS query handlers."""
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from ..nfo_config import logged
from .store import EventStore
from .types import Event, EventType

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


@logged
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


@logged
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
