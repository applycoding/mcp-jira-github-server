"""In-process sliding-window rate limit. It resets when the process restarts."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable


class RateLimitExceeded(Exception):
    """The caller exceeded the per-tool budget."""


class RateLimiter:
    def __init__(
        self,
        max_calls: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_calls < 0:
            raise ValueError("max_calls must be >= 0")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock or time.monotonic
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record one call or raise RateLimitExceeded. Zero disables the limit."""
        if self.max_calls == 0:
            return
        now = self._clock()
        with self._lock:
            recent = [stamp for stamp in self._calls[key] if now - stamp < self.window_seconds]
            if len(recent) >= self.max_calls:
                self._calls[key] = recent
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {key}. "
                    f"Limit is {self.max_calls} calls per {int(self.window_seconds)} seconds."
                )
            recent.append(now)
            self._calls[key] = recent
