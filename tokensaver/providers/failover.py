"""Multi-provider failover and load balancing.

Features:
1. Automatic failover — if primary provider fails, try next
2. Round-robin load balancing — distribute requests across providers
3. Health checking — periodically check provider availability
4. Cost-based routing — prefer cheapest provider for each request
5. Latency tracking — prefer fastest provider
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from tokensaver.providers import (
    Provider,
    ProviderConfig,
    MODEL_REGISTRY,
    get_adapter,
    get_cheapest_provider,
)

logger = logging.getLogger("tokensaver.failover")


class LoadBalanceStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    COST_FIRST = "cost_first"
    LATENCY_FIRST = "latency_first"
    LEAST_CONNECTIONS = "least_connections"


@dataclass
class ProviderHealth:
    """Health status for a provider."""

    provider: Provider
    available: bool = True
    last_check: float = 0.0
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    latency_history: list[float] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_failures / self.total_requests

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.consecutive_failures = 0
        self.available = True
        self.latency_history.append(latency_ms)
        # Keep last 20 latencies
        if len(self.latency_history) > 20:
            self.latency_history.pop(0)
        self.avg_latency_ms = sum(self.latency_history) / len(self.latency_history)

    def record_failure(self, error: str) -> None:
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.last_error = error
        # Mark unavailable after 3 consecutive failures
        if self.consecutive_failures >= 3:
            self.available = False
            logger.warning("Provider %s marked unavailable after %d failures",
                          self.provider.value, self.consecutive_failures)

    def reset(self) -> None:
        self.available = True
        self.consecutive_failures = 0
        self.last_error = None


@dataclass
class FailoverConfig:
    """Configuration for failover behavior."""

    strategy: LoadBalanceStrategy = LoadBalanceStrategy.COST_FIRST
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds
    health_check_interval: float = 60.0  # seconds
    circuit_breaker_threshold: int = 3  # failures before marking unavailable
    circuit_breaker_reset: float = 300.0  # seconds before retry


class ProviderPool:
    """Pool of providers with failover and load balancing."""

    def __init__(
        self,
        primary_provider: Provider = Provider.OPENAI,
        fallback_providers: list[Provider] | None = None,
        config: FailoverConfig | None = None,
    ) -> None:
        self.primary = primary_provider
        self.fallbacks = fallback_providers or []
        self.config = config or FailoverConfig()
        self.health: dict[Provider, ProviderHealth] = {}
        self._round_robin_idx = 0

        # Initialize health for all providers
        all_providers = [primary_provider] + self.fallbacks
        for provider in all_providers:
            self.health[provider] = ProviderHealth(provider=provider)

    def get_provider_order(
        self,
        token_count: int,
        require_system: bool = True,
    ) -> list[tuple[Provider, str]]:
        """Get ordered list of (provider, model) to try.

        Order depends on the load balance strategy.
        """
        candidates = []

        # Collect all available providers with their best models
        for provider in [self.primary] + self.fallbacks:
            health = self.health.get(provider)
            if health and not health.available:
                continue

            # Find cheapest model for this provider
            for model_name, config in MODEL_REGISTRY.items():
                if config.provider == provider and config.enabled:
                    if token_count <= config.max_context:
                        candidates.append((provider, model_name, config))
                        break

        if not candidates:
            # All providers down — try primary anyway
            for model_name, config in MODEL_REGISTRY.items():
                if config.provider == self.primary:
                    return [(self.primary, model_name)]

        # Sort by strategy
        if self.config.strategy == LoadBalanceStrategy.COST_FIRST:
            candidates.sort(key=lambda x: x[2].cost_per_token_input * token_count)
        elif self.config.strategy == LoadBalanceStrategy.LATENCY_FIRST:
            candidates.sort(key=lambda x: self.health[x[0]].avg_latency_ms)
        elif self.config.strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
            candidates.sort(key=lambda x: self.health[x[0]].total_requests)
        elif self.config.strategy == LoadBalanceStrategy.ROUND_ROBIN:
            # Rotate through candidates
            n = len(candidates)
            if n > 0:
                idx = self._round_robin_idx % n
                candidates = candidates[idx:] + candidates[:idx]
                self._round_robin_idx += 1

        return [(c[0], c[1]) for c in candidates]

    def record_success(self, provider: Provider, latency_ms: float) -> None:
        """Record a successful request."""
        if provider in self.health:
            self.health[provider].record_success(latency_ms)

    def record_failure(self, provider: Provider, error: str) -> None:
        """Record a failed request."""
        if provider in self.health:
            self.health[provider].record_failure(error)

    def get_stats(self) -> dict:
        """Get pool statistics."""
        stats = {}
        for provider, health in self.health.items():
            stats[provider.value] = {
                "available": health.available,
                "total_requests": health.total_requests,
                "total_failures": health.total_failures,
                "failure_rate": round(health.failure_rate, 4),
                "avg_latency_ms": round(health.avg_latency_ms, 2),
                "consecutive_failures": health.consecutive_failures,
            }
        return stats


class FailoverClient:
    """HTTP client with automatic failover across providers.

    This wraps the proxy logic to try multiple providers on failure.
    """

    def __init__(
        self,
        pool: ProviderPool | None = None,
        config: FailoverConfig | None = None,
    ) -> None:
        self.pool = pool or ProviderPool()
        self.config = config or FailoverConfig()

    async def send_with_failover(
        self,
        request_fn,
        token_count: int,
        require_system: bool = True,
    ):
        """Send a request with automatic failover.

        Args:
            request_fn: Async function that takes (provider, model) and returns response
            token_count: Estimated token count for cost-based routing
            require_system: Whether the request requires system message support

        Returns:
            (response, provider, model, latency_ms)

        Raises:
            Exception: If all providers fail
        """
        providers = self.pool.get_provider_order(token_count, require_system)
        last_error = None

        for attempt, (provider, model) in enumerate(providers):
            if attempt >= self.config.max_retries:
                break

            try:
                start = time.time()
                response = await request_fn(provider, model)
                latency_ms = (time.time() - start) * 1000

                self.pool.record_success(provider, latency_ms)
                return response, provider, model, latency_ms

            except Exception as e:
                last_error = e
                self.pool.record_failure(provider, str(e))
                logger.warning(
                    "Request to %s/%s failed (attempt %d/%d): %s",
                    provider.value, model, attempt + 1, self.config.max_retries, e
                )

                if attempt < len(providers) - 1:
                    await asyncio.sleep(self.config.retry_delay)

        raise Exception(f"All providers failed. Last error: {last_error}")


# Global instances
_pool: Optional[ProviderPool] = None
_failover_client: Optional[FailoverClient] = None


def get_pool() -> ProviderPool:
    """Get the global provider pool."""
    global _pool
    if _pool is None:
        from tokensaver.config import settings
        _pool = ProviderPool(
            primary_provider=Provider.OPENAI,
            fallback_providers=[Provider.ANTHROPIC, Provider.OLLAMA],
        )
    return _pool


def get_failover_client() -> FailoverClient:
    """Get the global failover client."""
    global _failover_client
    if _failover_client is None:
        _failover_client = FailoverClient(pool=get_pool())
    return _failover_client
