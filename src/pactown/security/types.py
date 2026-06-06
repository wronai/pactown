from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class AnomalyType(str, Enum):
    """Types of security anomalies."""

    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CONCURRENT_LIMIT_EXCEEDED = "concurrent_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    CPU_LIMIT_EXCEEDED = "cpu_limit_exceeded"
    SERVER_OVERLOADED = "server_overloaded"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    RAPID_RESTART = "rapid_restart"
    PORT_SCAN_DETECTED = "port_scan_detected"


class UserTier(str, Enum):
    """User tier levels with different resource limits."""

    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    ADMIN = "admin"


@dataclass
class AnomalyEvent:
    """Record of a security anomaly."""

    timestamp: datetime
    anomaly_type: AnomalyType
    user_id: Optional[str]
    service_id: Optional[str]
    details: str
    severity: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "anomaly_type": self.anomaly_type.value,
            "user_id": self.user_id,
            "service_id": self.service_id,
            "details": self.details,
            "severity": self.severity,
            "metadata": self.metadata,
        }

    def to_log_line(self) -> str:
        return (
            f"[{self.severity.upper()}] {self.anomaly_type.value} | "
            f"user={self.user_id} service={self.service_id} | {self.details}"
        )


@dataclass
class SecurityCheckResult:
    """Result of a security check."""

    allowed: bool
    reason: Optional[str] = None
    delay_seconds: float = 0.0
    anomaly: Optional[AnomalyEvent] = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "delay_seconds": self.delay_seconds,
            "anomaly": self.anomaly.to_dict() if self.anomaly else None,
        }
