"""Tests for multi-provider failover and load balancing."""

import pytest

from tokensaver.providers import Provider
from tokensaver.providers.failover import (
    ProviderPool,
    ProviderHealth,
    FailoverClient,
    FailoverConfig,
    LoadBalanceStrategy,
)


@pytest.fixture
def pool():
    return ProviderPool(
        primary_provider=Provider.OPENAI,
        fallback_providers=[Provider.ANTHROPIC, Provider.OLLAMA],
    )


def test_pool_initialization(pool):
    assert Provider.OPENAI in pool.health
    assert Provider.ANTHROPIC in pool.health
    assert Provider.OLLAMA in pool.health


def test_pool_all_available_by_default(pool):
    for health in pool.health.values():
        assert health.available is True


def test_record_success(pool):
    pool.record_success(Provider.OPENAI, 100.0)
    assert pool.health[Provider.OPENAI].total_requests == 1
    assert pool.health[Provider.OPENAI].avg_latency_ms == 100.0
    assert pool.health[Provider.OPENAI].consecutive_failures == 0


def test_record_failure(pool):
    pool.record_failure(Provider.OPENAI, "timeout")
    assert pool.health[Provider.OPENAI].total_failures == 1
    assert pool.health[Provider.OPENAI].consecutive_failures == 1
    assert pool.health[Provider.OPENAI].available is True  # still available


def test_circuit_breaker(pool):
    # 3 consecutive failures should mark unavailable
    for i in range(3):
        pool.record_failure(Provider.OPENAI, f"error_{i}")

    assert pool.health[Provider.OPENAI].available is False


def test_circuit_breaker_recovery(pool):
    # Mark unavailable
    for i in range(3):
        pool.record_failure(Provider.OPENAI, f"error_{i}")
    assert pool.health[Provider.OPENAI].available is False

    # Reset
    pool.health[Provider.OPENAI].reset()
    assert pool.health[Provider.OPENAI].available is True
    assert pool.health[Provider.OPENAI].consecutive_failures == 0


def test_get_provider_order_cost_first():
    config = FailoverConfig(strategy=LoadBalanceStrategy.COST_FIRST)
    pool = ProviderPool(
        primary_provider=Provider.OPENAI,
        fallback_providers=[Provider.OLLAMA],
        config=config,
    )

    order = pool.get_provider_order(token_count=100)
    # Ollama should be first (cheapest = free)
    assert order[0][0] == Provider.OLLAMA


def test_get_provider_order_excludes_unavailable(pool):
    # Mark OpenAI unavailable
    for i in range(3):
        pool.record_failure(Provider.OPENAI, f"error_{i}")

    order = pool.get_provider_order(token_count=100)
    providers = [p[0] for p in order]
    assert Provider.OPENAI not in providers


def test_get_provider_order_round_robin():
    config = FailoverConfig(strategy=LoadBalanceStrategy.ROUND_ROBIN)
    pool = ProviderPool(
        primary_provider=Provider.OPENAI,
        fallback_providers=[Provider.OLLAMA],
        config=config,
    )

    order1 = pool.get_provider_order(token_count=100)
    order2 = pool.get_provider_order(token_count=100)
    # Round robin should rotate
    assert order1 != order2 or len(order1) <= 1


def test_pool_stats(pool):
    pool.record_success(Provider.OPENAI, 50.0)
    pool.record_success(Provider.OPENAI, 100.0)
    pool.record_failure(Provider.ANTHROPIC, "error")

    stats = pool.get_stats()
    assert stats["openai"]["total_requests"] == 2
    assert stats["openai"]["total_failures"] == 0
    assert stats["anthropic"]["total_requests"] == 1
    assert stats["anthropic"]["total_failures"] == 1


def test_health_failure_rate():
    health = ProviderHealth(provider=Provider.OPENAI)
    health.record_success(100.0)
    health.record_success(100.0)
    health.record_failure("error")

    assert health.failure_rate == 1 / 3
    assert health.total_requests == 3


def test_health_latency_tracking():
    health = ProviderHealth(provider=Provider.OPENAI)
    for latency in [50.0, 100.0, 150.0]:
        health.record_success(latency)

    assert health.avg_latency_ms == 100.0
    assert len(health.latency_history) == 3


def test_health_latency_history_limit():
    health = ProviderHealth(provider=Provider.OPENAI)
    for i in range(25):
        health.record_success(float(i))

    assert len(health.latency_history) == 20  # capped at 20


def test_failover_config_defaults():
    config = FailoverConfig()
    assert config.strategy == LoadBalanceStrategy.COST_FIRST
    assert config.max_retries == 3
    assert config.retry_delay == 1.0


def test_failover_client_initialization():
    client = FailoverClient()
    assert client.pool is not None
    assert client.config is not None
