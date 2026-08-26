from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock


class LoginRateLimitError(RuntimeError):
    status_code = 429


class LoginAttemptLimiter:
    def __init__(self, *, max_failures: int = 10, window_seconds: int = 15 * 60):
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _active_failures(self, key: str, now: datetime) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = now.timestamp() - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return deque()
        return failures

    def check(self, key: str, *, now: datetime) -> None:
        with self._lock:
            if len(self._active_failures(key, now)) >= self.max_failures:
                raise LoginRateLimitError("登录尝试过于频繁，请稍后再试")

    def record_failure(self, key: str, *, now: datetime) -> None:
        with self._lock:
            failures = self._active_failures(key, now)
            if key not in self._failures:
                self._failures[key] = failures
            failures.append(now.timestamp())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
