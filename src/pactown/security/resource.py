from __future__ import annotations

import time
from threading import Lock
from typing import Dict

from ..nfo_config import logged


@logged
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
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                parts = line.split()[1:5]
                user, nice, system, idle = map(int, parts)
                total = user + nice + system + idle
                used = user + nice + system
                return (used / total) * 100 if total > 0 else 0.0
        except Exception:
            return 0.0

    def _get_memory_percent(self) -> float:
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
        except Exception:
            return 0.0

    def check_overload(self) -> tuple[bool, Dict[str, float]]:
        now = time.time()

        with self._lock:
            if now - self._last_check < self.check_interval:
                return self._is_overloaded, {}

            self._last_check = now
            cpu = self._get_cpu_percent()
            memory = self._get_memory_percent()
            self._is_overloaded = cpu > self.cpu_threshold or memory > self.memory_threshold

            return self._is_overloaded, {
                "cpu_percent": cpu,
                "memory_percent": memory,
                "cpu_threshold": self.cpu_threshold,
                "memory_threshold": self.memory_threshold,
            }

    def get_throttle_delay(self) -> float:
        is_overloaded, metrics = self.check_overload()
        if not is_overloaded:
            return 0.0

        cpu_over = max(0, metrics.get("cpu_percent", 0) - self.cpu_threshold)
        mem_over = max(0, metrics.get("memory_percent", 0) - self.memory_threshold)
        max_over = max(cpu_over, mem_over)
        return min(5.0, 0.5 + (max_over / 20.0) * 4.5)
