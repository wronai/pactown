from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .types import UserTier


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
    allowed_ports: Optional[List[int]] = None
    blocked: bool = False
    reason: Optional[str] = None

    @classmethod
    def from_tier(cls, user_id: str, tier: UserTier) -> "UserProfile":
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
