"""Convenience factories for CQRS handlers."""
from typing import Optional

from .commands import ProjectCommands, SecurityCommands, ServiceCommands
from .queries import ProjectQueries, SecurityQueries, ServiceQueries
from .store import EventStore, get_event_store

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
