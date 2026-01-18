"""
Security module for pactown.

Provides rate limiting, resource protection, user profiles with service limits,
throttling under load, and anomaly logging for admin monitoring.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, List, Optional, Any
import logging


# Configure logging for anomalies
logging.basicConfig(level=logging.INFO)
anomaly_logger = logging.getLogger("pactown.security.anomaly")


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
class UserProfile:
    """User profile with resource limits and permissions."""
    user_id: str
    tier: UserTier = UserTier.FREE
    max_concurrent_services: int = 2
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_requests_per_minute: int = 30
    max_services_per_hour: int = 10
    allowed_ports: Optional[List[int]] = None  # None = any port in range
    blocked: bool = False
    reason: Optional[str] = None
    
    @classmethod
    def from_tier(cls, user_id: str, tier: UserTier) -> "UserProfile":
        """Create profile with tier-based defaults."""
        tier_limits = {
            UserTier.FREE: {
                "max_concurrent_services": 2,
                "max_memory_mb": 256,
                "max_cpu_percent": 25,
                "max_requests_per_minute": 20,
                "max_services_per_hour": 5,
            },
            UserTier.BASIC: {
                "max_concurrent_services": 5,
                "max_memory_mb": 512,
                "max_cpu_percent": 50,
                "max_requests_per_minute": 60,
                "max_services_per_hour": 20,
            },
            UserTier.PRO: {
                "max_concurrent_services": 10,
                "max_memory_mb": 2048,
                "max_cpu_percent": 80,
                "max_requests_per_minute": 120,
                "max_services_per_hour": 50,
            },
            UserTier.ENTERPRISE: {
                "max_concurrent_services": 50,
                "max_memory_mb": 8192,
                "max_cpu_percent": 100,
                "max_requests_per_minute": 500,
                "max_services_per_hour": 200,
            },
            UserTier.ADMIN: {
                "max_concurrent_services": 100,
                "max_memory_mb": 16384,
                "max_cpu_percent": 100,
                "max_requests_per_minute": 1000,
                "max_services_per_hour": 1000,
            },
        }
        limits = tier_limits.get(tier, tier_limits[UserTier.FREE])
        return cls(user_id=user_id, tier=tier, **limits)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/JSON."""
        return {
            "user_id": self.user_id,
            "tier": self.tier.value,
            "max_concurrent_services": self.max_concurrent_services,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_percent": self.max_cpu_percent,
            "max_requests_per_minute": self.max_requests_per_minute,
            "max_services_per_hour": self.max_services_per_hour,
            "allowed_ports": self.allowed_ports,
            "blocked": self.blocked,
            "reason": self.reason,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        """Create from dictionary."""
        tier = UserTier(data.get("tier", "free"))
        return cls(
            user_id=data.get("user_id", "unknown"),
            tier=tier,
            max_concurrent_services=data.get("max_concurrent_services", 2),
            max_memory_mb=data.get("max_memory_mb", 512),
            max_cpu_percent=data.get("max_cpu_percent", 50),
            max_requests_per_minute=data.get("max_requests_per_minute", 30),
            max_services_per_hour=data.get("max_services_per_hour", 10),
            allowed_ports=data.get("allowed_ports"),
            blocked=data.get("blocked", False),
            reason=data.get("reason"),
        )


@dataclass
class AnomalyEvent:
    """Record of a security anomaly."""
    timestamp: datetime
    anomaly_type: AnomalyType
    user_id: Optional[str]
    service_id: Optional[str]
    details: str
    severity: str  # "low", "medium", "high", "critical"
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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AnomalyEvent:
        """Log an anomaly event."""
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
                self._events = self._events[-self.max_events:]
        
        # Log to file
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            anomaly_logger.error(f"Failed to write anomaly log: {e}")
        
        # Log to Python logger
        log_level = {
            "low": logging.DEBUG,
            "medium": logging.WARNING,
            "high": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(severity, logging.WARNING)
        anomaly_logger.log(log_level, event.to_log_line())
        
        # Call callback if provided
        if self.on_anomaly:
            try:
                self.on_anomaly(event)
            except Exception:
                pass
        
        return event
    
    def get_recent(self, count: int = 100) -> List[AnomalyEvent]:
        """Get recent anomaly events."""
        with self._lock:
            return self._events[-count:]
    
    def get_by_user(self, user_id: str, count: int = 100) -> List[AnomalyEvent]:
        """Get anomalies for a specific user."""
        with self._lock:
            return [e for e in self._events if e.user_id == user_id][-count:]
    
    def get_by_type(self, anomaly_type: AnomalyType, count: int = 100) -> List[AnomalyEvent]:
        """Get anomalies of a specific type."""
        with self._lock:
            return [e for e in self._events if e.anomaly_type == anomaly_type][-count:]


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10,
    ):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self._buckets: Dict[str, Dict] = {}
        self._lock = Lock()
    
    def _get_bucket(self, key: str) -> Dict:
        """Get or create a token bucket for a key."""
        now = time.time()
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = {
                    "tokens": self.burst_size,
                    "last_update": now,
                }
            bucket = self._buckets[key]
            
            # Refill tokens based on time elapsed
            elapsed = now - bucket["last_update"]
            refill = elapsed * (self.requests_per_minute / 60.0)
            bucket["tokens"] = min(self.burst_size, bucket["tokens"] + refill)
            bucket["last_update"] = now
            
            return bucket
    
    def check(self, key: str) -> bool:
        """Check if request is allowed (doesn't consume token)."""
        bucket = self._get_bucket(key)
        return bucket["tokens"] >= 1.0
    
    def consume(self, key: str) -> bool:
        """Try to consume a token. Returns True if allowed."""
        bucket = self._get_bucket(key)
        with self._lock:
            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return True
            return False
    
    def get_wait_time(self, key: str) -> float:
        """Get seconds to wait before next request is allowed."""
        bucket = self._get_bucket(key)
        if bucket["tokens"] >= 1.0:
            return 0.0
        tokens_needed = 1.0 - bucket["tokens"]
        return tokens_needed / (self.requests_per_minute / 60.0)


class ResourceMonitor:
    """Monitors system resources and detects overload."""
    
    def __init__(
        self,
        cpu_threshold: float = 80.0,
        memory_threshold: float = 85.0,
        check_interval: float = 5.0,
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.check_interval = check_interval
        self._last_check = 0.0
        self._is_overloaded = False
        self._lock = Lock()
    
    def _get_cpu_percent(self) -> float:
        """Get current CPU usage percentage."""
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                parts = line.split()[1:5]
                user, nice, system, idle = map(int, parts)
                total = user + nice + system + idle
                used = user + nice + system
                return (used / total) * 100 if total > 0 else 0.0
        except:
            return 0.0
    
    def _get_memory_percent(self) -> float:
        """Get current memory usage percentage."""
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                mem_info = {}
                for line in lines[:5]:
                    parts = line.split()
                    mem_info[parts[0].rstrip(":")] = int(parts[1])
                total = mem_info.get("MemTotal", 1)
                available = mem_info.get("MemAvailable", mem_info.get("MemFree", 0))
                used = total - available
                return (used / total) * 100 if total > 0 else 0.0
        except:
            return 0.0
    
    def check_overload(self) -> tuple[bool, Dict[str, float]]:
        """Check if system is overloaded. Returns (is_overloaded, metrics)."""
        now = time.time()
        
        with self._lock:
            if now - self._last_check < self.check_interval:
                return self._is_overloaded, {}
            
            self._last_check = now
            
            cpu = self._get_cpu_percent()
            memory = self._get_memory_percent()
            
            self._is_overloaded = (
                cpu > self.cpu_threshold or 
                memory > self.memory_threshold
            )
            
            return self._is_overloaded, {
                "cpu_percent": cpu,
                "memory_percent": memory,
                "cpu_threshold": self.cpu_threshold,
                "memory_threshold": self.memory_threshold,
            }
    
    def get_throttle_delay(self) -> float:
        """Get delay in seconds based on current load."""
        is_overloaded, metrics = self.check_overload()
        if not is_overloaded:
            return 0.0
        
        # Calculate delay based on how much we're over threshold
        cpu_over = max(0, metrics.get("cpu_percent", 0) - self.cpu_threshold)
        mem_over = max(0, metrics.get("memory_percent", 0) - self.memory_threshold)
        
        # Delay scales with overload: 0.5s base + up to 5s based on severity
        max_over = max(cpu_over, mem_over)
        return min(5.0, 0.5 + (max_over / 20.0) * 4.5)


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


class SecurityPolicy:
    """
    Main security policy enforcer for pactown.
    
    Combines rate limiting, resource monitoring, user profiles,
    and anomaly logging into a unified security layer.
    """
    
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
        self._user_services: Dict[str, List[str]] = {}  # user_id -> [service_ids]
        self._service_starts: Dict[str, List[float]] = {}  # user_id -> [timestamps]
        self._lock = Lock()
    
    def set_user_profile(self, profile: UserProfile) -> None:
        """Set or update a user profile."""
        with self._lock:
            self._user_profiles[profile.user_id] = profile
    
    def get_user_profile(self, user_id: str) -> UserProfile:
        """Get user profile, creating default if not exists."""
        with self._lock:
            if user_id not in self._user_profiles:
                self._user_profiles[user_id] = UserProfile.from_tier(user_id, UserTier.FREE)
            return self._user_profiles[user_id]
    
    def register_service(self, user_id: str, service_id: str) -> None:
        """Register a running service for a user."""
        with self._lock:
            if user_id not in self._user_services:
                self._user_services[user_id] = []
            if service_id not in self._user_services[user_id]:
                self._user_services[user_id].append(service_id)
            
            # Track service start time
            if user_id not in self._service_starts:
                self._service_starts[user_id] = []
            self._service_starts[user_id].append(time.time())
            
            # Clean old entries (older than 1 hour)
            cutoff = time.time() - 3600
            self._service_starts[user_id] = [
                t for t in self._service_starts[user_id] if t > cutoff
            ]
    
    def unregister_service(self, user_id: str, service_id: str) -> None:
        """Unregister a stopped service."""
        with self._lock:
            if user_id in self._user_services:
                if service_id in self._user_services[user_id]:
                    self._user_services[user_id].remove(service_id)
    
    def get_user_service_count(self, user_id: str) -> int:
        """Get number of running services for a user."""
        with self._lock:
            return len(self._user_services.get(user_id, []))
    
    def get_services_started_last_hour(self, user_id: str) -> int:
        """Get number of services started in the last hour."""
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
        """
        Check if a user can start a new service.
        
        Returns SecurityCheckResult with allowed status and any required delay.
        """
        profile = self.get_user_profile(user_id)
        
        # Check if user is blocked
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
        
        # Check rate limit
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
        
        # Check concurrent service limit
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
        
        # Check hourly service limit
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
        
        # Check port restrictions
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
        
        # Check system resources
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
            
            # For free tier, deny during overload
            if profile.tier == UserTier.FREE:
                return SecurityCheckResult(
                    allowed=False,
                    reason="Server is currently overloaded. Please try again later.",
                    delay_seconds=delay,
                    anomaly=anomaly,
                )
            
            # For paid tiers, allow but with delay
            return SecurityCheckResult(
                allowed=True,
                reason=f"Server under load, request delayed by {delay:.1f}s",
                delay_seconds=delay,
                anomaly=anomaly,
            )
        
        # Check for rapid restart pattern (potential abuse)
        starts = self._service_starts.get(user_id, [])
        recent_starts = [t for t in starts if time.time() - t < 60]  # Last minute
        if len(recent_starts) >= 5:
            anomaly = self.anomaly_logger.log(
                AnomalyType.RAPID_RESTART,
                f"User {user_id} showing rapid restart pattern ({len(recent_starts)} in 60s)",
                user_id=user_id,
                service_id=service_id,
                severity="medium",
                metadata={"restarts_last_minute": len(recent_starts)},
            )
            # Allow but log for monitoring
        
        # Consume rate limit token
        self.rate_limiter.consume(rate_key)
        
        return SecurityCheckResult(allowed=True)
    
    def get_anomaly_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get summary of anomalies for admin dashboard."""
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
                e.to_dict() for e in recent 
                if e.severity == "critical"
            ][-10:],
        }


# Global default policy instance
_default_policy: Optional[SecurityPolicy] = None


def get_security_policy() -> SecurityPolicy:
    """Get the global security policy instance."""
    global _default_policy
    if _default_policy is None:
        _default_policy = SecurityPolicy()
    return _default_policy


def set_security_policy(policy: SecurityPolicy) -> None:
    """Set the global security policy instance."""
    global _default_policy
    _default_policy = policy
