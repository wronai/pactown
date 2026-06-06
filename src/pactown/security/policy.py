from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from ..nfo_config import logged
from .anomaly import AnomalyLogger
from .profiles import UserProfile
from .rate_limit import RateLimiter
from .resource import ResourceMonitor
from .types import AnomalyEvent, AnomalyType, SecurityCheckResult, UserTier


@logged
class SecurityPolicy:
    """Main security policy enforcer for pactown."""

    def __init__(
        self,
        anomaly_log_path: Optional[Path] = None,
        default_rate_limit: int = 60,
        cpu_threshold: float = 80.0,
        memory_threshold: float = 85.0,
        on_anomaly: Optional[Callable[[AnomalyEvent], None]] = None,
    ):
        self.anomaly_logger = AnomalyLogger(
            log_path=anomaly_log_path,
            on_anomaly=on_anomaly,
        )
        self.rate_limiter = RateLimiter(requests_per_minute=default_rate_limit)
        self.resource_monitor = ResourceMonitor(
            cpu_threshold=cpu_threshold,
            memory_threshold=memory_threshold,
        )

        self._user_profiles: Dict[str, UserProfile] = {}
        self._user_services: Dict[str, List[str]] = {}
        self._service_starts: Dict[str, List[float]] = {}
        self._lock = Lock()

    def set_user_profile(self, profile: UserProfile) -> None:
        with self._lock:
            self._user_profiles[profile.user_id] = profile

    def get_user_profile(self, user_id: str) -> UserProfile:
        with self._lock:
            if user_id not in self._user_profiles:
                self._user_profiles[user_id] = UserProfile.from_tier(user_id, UserTier.FREE)
            return self._user_profiles[user_id]

    def register_service(self, user_id: str, service_id: str) -> None:
        with self._lock:
            if user_id not in self._user_services:
                self._user_services[user_id] = []
            if service_id not in self._user_services[user_id]:
                self._user_services[user_id].append(service_id)

            if user_id not in self._service_starts:
                self._service_starts[user_id] = []
            self._service_starts[user_id].append(time.time())

            cutoff = time.time() - 3600
            self._service_starts[user_id] = [
                t for t in self._service_starts[user_id] if t > cutoff
            ]

    def unregister_service(self, user_id: str, service_id: str) -> None:
        with self._lock:
            if user_id in self._user_services:
                if service_id in self._user_services[user_id]:
                    self._user_services[user_id].remove(service_id)

    def get_user_service_count(self, user_id: str) -> int:
        with self._lock:
            return len(self._user_services.get(user_id, []))

    def get_services_started_last_hour(self, user_id: str) -> int:
        with self._lock:
            cutoff = time.time() - 3600
            starts = self._service_starts.get(user_id, [])
            return len([t for t in starts if t > cutoff])

    async def check_can_start_service(
        self,
        user_id: str,
        service_id: str,
        port: Optional[int] = None,
    ) -> SecurityCheckResult:
        profile = self.get_user_profile(user_id)

        if profile.blocked:
            anomaly = self.anomaly_logger.log(
                AnomalyType.UNAUTHORIZED_ACCESS,
                f"Blocked user {user_id} attempted to start service",
                user_id=user_id,
                service_id=service_id,
                severity="high",
            )
            return SecurityCheckResult(
                allowed=False,
                reason=f"User blocked: {profile.reason or 'No reason provided'}",
                anomaly=anomaly,
            )

        rate_key = f"user:{user_id}:start"
        if not self.rate_limiter.check(rate_key):
            wait_time = self.rate_limiter.get_wait_time(rate_key)
            anomaly = self.anomaly_logger.log(
                AnomalyType.RATE_LIMIT_EXCEEDED,
                f"User {user_id} exceeded rate limit for service starts",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
                metadata={"wait_time": wait_time},
            )
            return SecurityCheckResult(
                allowed=False,
                reason=f"Rate limit exceeded. Wait {wait_time:.1f}s",
                delay_seconds=wait_time,
                anomaly=anomaly,
            )

        current_count = self.get_user_service_count(user_id)
        if current_count >= profile.max_concurrent_services:
            anomaly = self.anomaly_logger.log(
                AnomalyType.CONCURRENT_LIMIT_EXCEEDED,
                f"User {user_id} at max concurrent services ({current_count}/{profile.max_concurrent_services})",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
                metadata={
                    "current": current_count,
                    "max": profile.max_concurrent_services,
                },
            )
            return SecurityCheckResult(
                allowed=False,
                reason=f"Max concurrent services reached ({current_count}/{profile.max_concurrent_services}). Stop a service first.",
                anomaly=anomaly,
            )

        hourly_count = self.get_services_started_last_hour(user_id)
        if hourly_count >= profile.max_services_per_hour:
            anomaly = self.anomaly_logger.log(
                AnomalyType.RATE_LIMIT_EXCEEDED,
                f"User {user_id} exceeded hourly service limit ({hourly_count}/{profile.max_services_per_hour})",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
            )
            return SecurityCheckResult(
                allowed=False,
                reason=f"Hourly service limit reached ({hourly_count}/{profile.max_services_per_hour}). Try again later.",
                anomaly=anomaly,
            )

        if port and profile.allowed_ports:
            if port not in profile.allowed_ports:
                anomaly = self.anomaly_logger.log(
                    AnomalyType.UNAUTHORIZED_ACCESS,
                    f"User {user_id} attempted to use restricted port {port}",
                    user_id=user_id,
                    service_id=service_id,
                    severity="high",
                    metadata={"port": port, "allowed": profile.allowed_ports},
                )
                return SecurityCheckResult(
                    allowed=False,
                    reason=f"Port {port} not allowed for your account",
                    anomaly=anomaly,
                )

        is_overloaded, metrics = self.resource_monitor.check_overload()
        if is_overloaded:
            delay = self.resource_monitor.get_throttle_delay()
            anomaly = self.anomaly_logger.log(
                AnomalyType.SERVER_OVERLOADED,
                f"Server overloaded, throttling user {user_id}",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
                metadata=metrics,
            )

            if profile.tier == UserTier.FREE:
                return SecurityCheckResult(
                    allowed=False,
                    reason="Server is currently overloaded. Please try again later.",
                    delay_seconds=delay,
                    anomaly=anomaly,
                )

            return SecurityCheckResult(
                allowed=True,
                reason=f"Server under load, request delayed by {delay:.1f}s",
                delay_seconds=delay,
                anomaly=anomaly,
            )

        starts = self._service_starts.get(user_id, [])
        recent_starts = [t for t in starts if time.time() - t < 60]
        if len(recent_starts) >= 5:
            self.anomaly_logger.log(
                AnomalyType.RAPID_RESTART,
                f"User {user_id} showing rapid restart pattern ({len(recent_starts)} in 60s)",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
                metadata={"restarts_last_minute": len(recent_starts)},
            )

        self.rate_limiter.consume(rate_key)
        return SecurityCheckResult(allowed=True)

    def get_anomaly_summary(self, hours: int = 24) -> Dict[str, Any]:
        cutoff = datetime.now(UTC).timestamp() - (hours * 3600)
        recent = [
            e for e in self.anomaly_logger.get_recent(1000)
            if e.timestamp.timestamp() > cutoff
        ]

        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        by_user: Dict[str, int] = {}

        for event in recent:
            by_type[event.anomaly_type.value] = by_type.get(event.anomaly_type.value, 0) + 1
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            if event.user_id:
                by_user[event.user_id] = by_user.get(event.user_id, 0) + 1

        return {
            "period_hours": hours,
            "total_anomalies": len(recent),
            "by_type": by_type,
            "by_severity": by_severity,
            "top_users": dict(sorted(by_user.items(), key=lambda x: -x[1])[:10]),
            "recent_critical": [
                e.to_dict() for e in recent if e.severity == "critical"
            ][-10:],
        }


_default_policy: Optional[SecurityPolicy] = None


def get_security_policy() -> SecurityPolicy:
    global _default_policy
    if _default_policy is None:
        _default_policy = SecurityPolicy()
    return _default_policy


def set_security_policy(policy: SecurityPolicy) -> None:
    global _default_policy
    _default_policy = policy
