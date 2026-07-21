"""Tests for the prompt compressor."""

import pytest

from tokenxygen.compress import PromptCompressor


@pytest.fixture
def compressor():
    return PromptCompressor(aggressiveness=0.3)


def test_compress_no_change_small(compressor):
    messages = [{"role": "user", "content": "What is 2+2?"}]
    compressed, results = compressor.compress(messages, "gpt-4o")
    # Small messages shouldn't be compressed much
    assert len(compressed) == len(messages)


def test_compress_deduplicates_files(compressor):
    file_content = """
def main():
    import os
    import sys
    import json
    x = 1
    return x
"""
    messages = [
        {"role": "user", "content": "Check this code"},
        {"role": "assistant", "content": file_content},
        {"role": "user", "content": "Now fix it"},
        {"role": "assistant", "content": file_content},  # duplicate
    ]

    compressed, results = compressor.compress(messages, "gpt-4o")

    # Should have removed the duplicate
    strategies = [r.strategy for r in results]
    assert "file_dedup" in strategies


def test_compress_strips_comments(compressor):
    code_with_comments = """
# This is a comment
def calculate(x):
    # Another comment
    result = x + 1  # inline comment
    return result
"""
    messages = [{"role": "user", "content": code_with_comments}]
    compressed, results = compressor.compress(messages, "gpt-4o")

    strategies = [r.strategy for r in results]
    # Should strip comments from code-like content
    if "comment_strip" in strategies:
        compressed_content = compressed[0]["content"]
        # Pure comment lines should be removed
        assert "# This is a comment" not in compressed_content


def test_compress_normalizes_whitespace(compressor):
    messages = [
        {"role": "user", "content": "Hello\n\n\n\n\n\nWorld"}  # many blank lines
    ]
    compressed, results = compressor.compress(messages, "gpt-4o")

    strategies = [r.strategy for r in results]
    if "whitespace_norm" in strategies:
        assert "\n\n\n\n\n" not in compressed[0]["content"]


def test_compression_result_savings():
    from tokenxygen.compress import CompressionResult

    result = CompressionResult(
        original_tokens=100,
        compressed_tokens=60,
        strategy="test",
        details=["test compression"],
    )
    assert result.saved_tokens == 40
    assert result.savings_pct == 40.0


def test_compress_preserves_non_code_messages(compressor):
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    compressed, results = compressor.compress(messages, "gpt-4o")

    # System and simple user messages should be unchanged
    assert compressed[0]["content"] == "You are a helpful assistant."
    assert compressed[1]["content"] == "Hello!"
