"""Append-only event store."""
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import asyncio
import json

from ..nfo_config import logged
from .types import Event, EventType

@logged
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

