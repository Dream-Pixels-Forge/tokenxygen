"""Tests for the semantic cache."""

import pytest

from tokenxygen.cache import SemanticCache, DatabasePool


@pytest.fixture
def tmp_cache(tmp_path):
    """Create a temporary cache instance."""
    db_path = str(tmp_path / "test_cache.db")
    cache = SemanticCache.__new__(SemanticCache)
    cache.db_path = db_path
    cache.threshold = 0.92
    cache.max_entries = 1000
    cache.ttl = 86400
    cache._pool = DatabasePool(db_path)
    return cache


def test_cache_miss(tmp_cache):
    messages = [{"role": "user", "content": "Hello"}]
    result = tmp_cache.get(messages, "gpt-4o")
    assert result is None


def test_cache_put_and_get(tmp_cache):
    messages = [{"role": "user", "content": "What is Python?"}]
    response = {"choices": [{"message": {"content": "Python is a programming language."}}]}

    tmp_cache.put(messages, response, "gpt-4o", tokens_used=20)
    result = tmp_cache.get(messages, "gpt-4o")

    assert result is not None
    assert result["choices"][0]["message"]["content"] == "Python is a programming language."


def test_cache_miss_different_model(tmp_cache):
    messages = [{"role": "user", "content": "What is Python?"}]
    response = {"choices": [{"message": {"content": "Answer"}}]}

    tmp_cache.put(messages, response, "gpt-4o", tokens_used=20)
    result = tmp_cache.get(messages, "gpt-4o-mini")  # different model

    assert result is None  # should miss


def test_cache_stats(tmp_cache):
    messages = [{"role": "user", "content": "Test"}]
    response = {"choices": [{"message": {"content": "OK"}}]}

    tmp_cache.put(messages, response, "gpt-4o", tokens_used=10)
    stats = tmp_cache.stats()

    assert stats["entries"] == 1
    assert stats["tokens_saved"] == 10
    assert stats["total_hits"] == 0

    # Get it once to increment hits
    tmp_cache.get(messages, "gpt-4o")
    stats = tmp_cache.stats()
    assert stats["total_hits"] == 1


def test_cache_clear(tmp_cache):
    messages = [{"role": "user", "content": "Test"}]
    response = {"choices": [{"message": {"content": "OK"}}]}

    tmp_cache.put(messages, response, "gpt-4o", tokens_used=10)
    assert tmp_cache.stats()["entries"] == 1

    cleared = tmp_cache.clear()
    assert cleared == 1
    assert tmp_cache.stats()["entries"] == 0
