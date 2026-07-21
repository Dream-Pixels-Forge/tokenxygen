"""Rate limiting with Redis support and in-memory fallback.

Features:
1. Redis-backed rate limiting for distributed deployments
2. In-memory fallback for single-instance deployments
3. Sliding window algorithm for accurate limiting
4. Thread-safe implementation
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

from tokenxygen.config import settings

import logging

logger = logging.getLogger("tokenxygen.ratelimit")


class RateLimitBackend(ABC):
    """Abstract base class for rate limit backends."""

    @abstractmethod
    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> bool:
        """Check if a request is allowed under the rate limit."""
        ...

    @abstractmethod
    def get_usage(self, key: str, window_seconds: float) -> int:
        """Get current request count for a key within the window."""
        ...

    @abstractmethod
    def clear(self, key: str) -> None:
        """Clear rate limit data for a key."""
        ...


class InMemoryBackend(RateLimitBackend):
    """Thread-safe in-memory rate limiter using sliding window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, list[float]] = {}

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> bool:
        now = time.time()

        with self._lock:
            if key not in self._store:
                self._store[key] = []

            # Remove expired entries
            self._store[key] = [
                t for t in self._store[key]
                if now - t < window_seconds
            ]

            if len(self._store[key]) >= max_requests:
                return False

            self._store[key].append(now)
            return True

    def get_usage(self, key: str, window_seconds: float) -> int:
        now = time.time()

        with self._lock:
            if key not in self._store:
                return 0

            return len([
                t for t in self._store[key]
                if now - t < window_seconds
            ])

    def clear(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


class RedisBackend(RateLimitBackend):
    """Redis-backed rate limiter using sliding window with sorted sets.

    Requires: pip install redis
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            self._available = True
            logger.info("Redis rate limiter connected: %s", redis_url)
        except ImportError:
            logger.warning("redis package not installed, falling back to in-memory")
            self._redis = None
            self._available = False
        except Exception as e:
            logger.warning("Redis connection failed: %s, falling back to in-memory", e)
            self._redis = None
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and self._redis is not None

    async def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> bool:
        if not self.is_available:
            return False

        now = time.time()
        window_start = now - window_seconds
        rate_key = f"ratelimit:{key}"

        try:
            pipe = self._redis.pipeline()
            # Remove old entries
            pipe.zremrangebyscore(rate_key, 0, window_start)
            # Count current entries
            pipe.zcard(rate_key)
            # Add current request
            pipe.zadd(rate_key, {str(now): now})
            # Set expiry
            pipe.expire(rate_key, int(window_seconds) + 1)

            results = await pipe.execute()
            current_count = results[1]

            return current_count < max_requests
        except Exception as e:
            logger.warning("Redis rate limit check failed: %s", e)
            return True  # Fail open

    async def get_usage(self, key: str, window_seconds: float) -> int:
        if not self.is_available:
            return 0

        now = time.time()
        window_start = now - window_seconds
        rate_key = f"ratelimit:{key}"

        try:
            # Remove old entries and count
            await self._redis.zremrangebyscore(rate_key, 0, window_start)
            return await self._redis.zcard(rate_key)
        except Exception:
            return 0

    async def clear(self, key: str) -> None:
        if not self.is_available:
            return

        rate_key = f"ratelimit:{key}"
        try:
            await self._redis.delete(rate_key)
        except Exception:
            pass


class RateLimiter:
    """Unified rate limiter with automatic backend selection."""

    def __init__(self, backend: Optional[RateLimitBackend] = None) -> None:
        if backend is not None:
            self._backend = backend
        else:
            # Try Redis if configured, otherwise use in-memory
            redis_url = getattr(settings, 'redis_url', None)
            if redis_url:
                redis_backend = RedisBackend(redis_url)
                if redis_backend.is_available:
                    self._backend = redis_backend
                else:
                    self._backend = InMemoryBackend()
            else:
                self._backend = InMemoryBackend()

    def is_allowed(
        self,
        client_ip: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[float] = None,
    ) -> bool:
        """Check if a request from client_ip is allowed."""
        max_requests = max_requests or settings.proxy.rate_limit_requests
        window_seconds = window_seconds or settings.proxy.rate_limit_window

        key = f"ip:{client_ip}"
        return self._backend.is_allowed(key, max_requests, window_seconds)

    def get_usage(self, client_ip: str, window_seconds: Optional[float] = None) -> int:
        """Get current request count for a client."""
        window_seconds = window_seconds or settings.proxy.rate_limit_window
        key = f"ip:{client_ip}"
        return self._backend.get_usage(key, window_seconds)

    def clear(self, client_ip: str) -> None:
        """Clear rate limit data for a client."""
        key = f"ip:{client_ip}"
        self._backend.clear(key)


# Global singleton
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
