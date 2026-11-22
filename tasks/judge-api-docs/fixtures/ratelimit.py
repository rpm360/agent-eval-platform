"""Token bucket rate limiter."""

import time


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self._tokens = float(capacity)
        self._last = time.monotonic()

    def allow(self, cost: int = 1) -> bool:
        if cost <= 0 or cost > self.capacity:
            raise ValueError("cost must be in 1..capacity")
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.refill_rate)
        self._last = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False
