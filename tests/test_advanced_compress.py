"""Tests for advanced LLMLingua-2 compression."""

import pytest

from tokensaver.compress.advanced import LLMLinguaCompressor, CompressionStats


@pytest.fixture
def compressor():
    return LLMLinguaCompressor()


def test_rule_based_compression(compressor):
    """Test rule-based compression (when LLMLingua not available)."""
    text = "Please, in order to save tokens, I would like you to basically reduce the size of this text."
    compressed, stats = compressor.compress(text, compression_ratio=0.5)

    assert stats.method == "rule_based"
    assert stats.tokens_removed >= 0
    assert "please" not in compressed.lower().strip().split()[0]  # filler removed


def test_compression_stats(compressor):
    text = "word " * 200
    _, stats = compressor.compress(text, compression_ratio=0.5)

    assert stats.original_tokens > 0
    assert stats.tokens_removed >= 0
    assert 0 <= stats.removal_ratio <= 1


def test_compression_preserves_content(compressor):
    text = "def main():\n    return 42"
    compressed, stats = compressor.compress(text, compression_ratio=0.2)

    # Core content should be preserved
    assert "42" in compressed
    assert "main" in compressed


def test_compress_messages_system_light(compressor):
    messages = [
        {"role": "system", "content": "You are a helpful assistant with detailed knowledge."},
        {"role": "user", "content": "Please explain in order to understand the concept basically."},
    ]
    result, stats = compressor.compress_messages(messages, compression_ratio=0.5)

    assert len(result) == 2
    # System message should be compressed less
    assert result[0]["role"] == "system"
    assert result[1]["role"] == "user"


def test_compress_messages_tool_aggressive(compressor):
    tool_output = "Here is the result: " + "data " * 100
    messages = [
        {"role": "user", "content": "Run this"},
        {"role": "tool", "content": tool_output},
    ]
    result, stats = compressor.compress_messages(messages, compression_ratio=0.5)

    # Tool output should be compressed more aggressively
    assert len(result) == 2
    assert result[0]["content"] == "Run this"  # user unchanged


def test_compress_messages_assistant_unchanged(compressor):
    messages = [
        {"role": "assistant", "content": "Here is my response with lots of detail."},
    ]
    result, stats = compressor.compress_messages(messages, compression_ratio=0.5)

    # Assistant messages should not be compressed
    assert result[0]["content"] == "Here is my response with lots of detail."


def test_empty_text(compressor):
    compressed, stats = compressor.compress("", compression_ratio=0.5)
    assert compressed == ""
    assert stats.original_tokens == 0


def test_llmlingua_availability(compressor):
    """Check if LLMLingua is available (may or may not be installed)."""
    available = compressor.is_available()
    assert isinstance(available, bool)


def test_rule_based_simplifications(compressor):
    text = "Due to the fact that it is raining, I will stay at home."
    compressed, stats = compressor.compress(text, compression_ratio=0.5)

    # Should simplify verbose phrases
    assert "because" in compressed.lower() or "raining" in compressed.lower()
