from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, List, Optional

from ..nfo_config import get_logger, logged
from .types import AnomalyEvent, AnomalyType

anomaly_logger = get_logger("pactown.security.anomaly")


@logged
class AnomalyLogger:
    """Logs security anomalies for admin review."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_events: int = 10000,
        on_anomaly: Optional[Callable[[AnomalyEvent], None]] = None,
    ):
        import tempfile

        default_log = tempfile.gettempdir() + "/pactown-anomalies.jsonl"
        self.log_path = log_path or Path(os.environ.get("PACTOWN_ANOMALY_LOG", default_log))
        self.max_events = max_events
        self.on_anomaly = on_anomaly
        self._events: List[AnomalyEvent] = []
        self._lock = Lock()

    def log(
        self,
        anomaly_type: AnomalyType,
        details: str,
        user_id: Optional[str] = None,
        service_id: Optional[str] = None,
        severity: str = "medium",
        metadata: Optional[Dict] = None,
    ) -> AnomalyEvent:
        event = AnomalyEvent(
            timestamp=datetime.now(UTC),
            anomaly_type=anomaly_type,
            user_id=user_id,
            service_id=service_id,
            details=details,
            severity=severity,
            metadata=metadata or {},
        )

        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events :]

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            anomaly_logger.error(f"Failed to write anomaly log: {e}")

        log_level = {
            "low": logging.DEBUG,
            "medium": logging.WARNING,
            "high": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(severity, logging.WARNING)
        anomaly_logger.log(log_level, event.to_log_line())

        if self.on_anomaly:
            try:
                self.on_anomaly(event)
            except Exception:
                pass

        return event

    def get_recent(self, count: int = 100) -> List[AnomalyEvent]:
        with self._lock:
            return self._events[-count:]

    def get_by_user(self, user_id: str, count: int = 100) -> List[AnomalyEvent]:
        with self._lock:
            return [e for e in self._events if e.user_id == user_id][-count:]

    def get_by_type(self, anomaly_type: AnomalyType, count: int = 100) -> List[AnomalyEvent]:
        with self._lock:
            return [e for e in self._events if e.anomaly_type == anomaly_type][-count:]
