from __future__ import annotations

import time
from threading import Lock
from typing import Dict

from ..nfo_config import logged


@logged
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
        now = time.time()
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = {
                    "tokens": self.burst_size,
                    "last_update": now,
                }
            bucket = self._buckets[key]
            elapsed = now - bucket["last_update"]
            refill = elapsed * (self.requests_per_minute / 60.0)
            bucket["tokens"] = min(self.burst_size, bucket["tokens"] + refill)
            bucket["last_update"] = now
            return bucket

    def check(self, key: str) -> bool:
        bucket = self._get_bucket(key)
        return bucket["tokens"] >= 1.0

    def consume(self, key: str) -> bool:
        bucket = self._get_bucket(key)
        with self._lock:
            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return True
            return False

    def get_wait_time(self, key: str) -> float:
        bucket = self._get_bucket(key)
        if bucket["tokens"] >= 1.0:
            return 0.0
        tokens_needed = 1.0 - bucket["tokens"]
        return tokens_needed / (self.requests_per_minute / 60.0)
