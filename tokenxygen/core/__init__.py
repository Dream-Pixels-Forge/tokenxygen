"""Core token counting and estimation utilities."""

from __future__ import annotations

import hashlib
import tiktoken


# Cache encodings per model family
_ENCODING_CACHE: dict[str, tiktoken.Encoding] = {}
_TOKEN_CACHE_MAX = 1024
_TOKEN_CACHE: dict[str, int] = {}

MODEL_TO_ENCODING: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude-3": "cl100k_base",  # approximate
    "claude-3.5": "cl100k_base",
    "default": "cl100k_base",
}


def get_encoding(model: str = "default") -> tiktoken.Encoding:
    """Get tiktoken encoding for a model, with caching."""
    if model not in _ENCODING_CACHE:
        encoding_name = MODEL_TO_ENCODING.get(model, MODEL_TO_ENCODING["default"])
        _ENCODING_CACHE[model] = tiktoken.get_encoding(encoding_name)
    return _ENCODING_CACHE[model]


def count_tokens(text: str, model: str = "default") -> int:
    """Count tokens in a string with caching."""
    # Cache lookup for repeated text
    cache_key = hashlib.md5((model + text[:1000]).encode()).hexdigest()
    if cache_key in _TOKEN_CACHE:
        return _TOKEN_CACHE[cache_key]
    
    enc = get_encoding(model)
    count = len(enc.encode(text))
    
    # Simple LRU: clear if full
    if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[cache_key] = count
    
    return count


def count_message_tokens(messages: list[dict], model: str = "default") -> int:
    """Count tokens in a chat messages array.

    Adds ~4 tokens overhead per message for formatting.
    """
    enc = get_encoding(model)
    total = 0
    for msg in messages:
        total += 4  # message formatting overhead
        for key, value in msg.items():
            if isinstance(value, str):
                total += len(enc.encode(value))
    total += 2  # priming token
    return total


def estimate_cost_usd(tokens: int, model: str = "gpt-4o") -> float:
    """Estimate cost in USD for a given token count and model.

    Prices per 1M tokens (as of early 2025).
    """
    prices = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
    }
    model_key = model if model in prices else "gpt-4o"
    price = prices[model_key]["input"]  # assume input tokens for prompt
    return (tokens / 1_000_000) * price


def content_hash(text: str) -> str:
    """Fast content hash for deduplication."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def truncate_to_tokens(text: str, max_tokens: int, model: str = "default") -> str:
    """Truncate text to fit within max_tokens."""
    enc = get_encoding(model)
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])
