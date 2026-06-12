"""Tests for core token counting utilities."""

from tokensaver.core import count_tokens, count_message_tokens, estimate_cost_usd, content_hash, truncate_to_tokens


def test_count_tokens():
    text = "Hello, world! This is a test."
    tokens = count_tokens(text)
    assert tokens > 0
    assert tokens < 50  # this short text shouldn't be many tokens


def test_count_message_tokens():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2+2?"},
    ]
    tokens = count_message_tokens(messages)
    assert tokens > 0
    # Should be roughly the sum of both messages + overhead
    assert tokens > count_tokens("You are a helpful assistant.What is 2+2?")


def test_estimate_cost_usd():
    cost_1k = estimate_cost_usd(1000, "gpt-4o")
    cost_10k = estimate_cost_usd(10000, "gpt-4o")
    assert cost_10k > cost_1k
    assert cost_1k > 0
    # gpt-4o is $2.50/1M input tokens → 1K tokens = $0.0025
    assert abs(cost_1k - 0.0025) < 0.0001


def test_estimate_cost_cheap_model():
    cost_4o = estimate_cost_usd(10000, "gpt-4o")
    cost_mini = estimate_cost_usd(10000, "gpt-4o-mini")
    assert cost_mini < cost_4o  # mini should be cheaper


def test_content_hash():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    h3 = content_hash("hello world!")
    assert h1 == h2  # same input → same hash
    assert h1 != h3  # different input → different hash
    assert len(h1) == 16  # truncated to 16 chars


def test_truncate_to_tokens():
    long_text = "word " * 1000  # ~500 tokens
    truncated = truncate_to_tokens(long_text, 10)
    tokens = count_tokens(truncated)
    assert tokens <= 10
    # Should be a prefix of the original
    assert truncated.startswith("word")
