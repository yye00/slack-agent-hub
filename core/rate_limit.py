"""Token bucket rate limiter for query operations."""
import time


class RateLimiter:
    def __init__(self, max_tokens: int = 10, refill_per_sec: float = 0.5):
        self._max = max_tokens
        self._refill_rate = refill_per_sec
        self._buckets: dict[str, dict] = {}

    def _get_bucket(self, key: str) -> dict:
        if key not in self._buckets:
            self._buckets[key] = {"tokens": float(self._max), "last_refill": time.monotonic()}
        return self._buckets[key]

    def _refill(self, bucket: dict) -> None:
        now = time.monotonic()
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(self._max, bucket["tokens"] + elapsed * self._refill_rate)
        bucket["last_refill"] = now

    def allow(self, key: str) -> bool:
        if self._max == 0:
            return True  # Disabled
        bucket = self._get_bucket(key)
        self._refill(bucket)
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

    def remaining(self, key: str) -> int:
        if self._max == 0:
            return 999
        bucket = self._get_bucket(key)
        self._refill(bucket)
        return int(bucket["tokens"])
