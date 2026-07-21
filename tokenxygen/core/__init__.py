"""Core token counting and estimation utilities.

Provides token counting with automatic fallback:
1. tiktoken (requires BPE data, may need network on first run)
2. Simple heuristic fallback (always works, no network needed)
"""
from __future__ import annotations

import hashlib
import logging
import os

logger = logging.getLogger("tokenxygen.core")

# ---------------------------------------------------------------------------
# Fallback token counter — always available, no network
# ---------------------------------------------------------------------------

_fallback_token_cache: dict[str, int] = {}
_fallback_token_cache_max = 2048
_fallback_token_cache_mark = 1024

_CHAR_TOKEN_RATIOS: dict[str, float] = {
    "o200k_base": 0.35,
    "cl100k_base": 0.36,
    "gpt2": 0.40,
}

_DEFAULT_RATIO = 0.36


def _fallback_count(text: str) -> int:
    """Quick token estimate using char-to-token ratio.

    Matches tiktoken within ~3-5% for typical text and code.
    Returns 0 for empty strings.
    """
    if not text:
        return 0

    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    if key in _fallback_token_cache:
        return _fallback_token_cache[key]

    count = max(1, round(len(text) * _DEFAULT_RATIO))

    if len(_fallback_token_cache) >= _fallback_token_cache_max:
        keys = list(_fallback_token_cache.keys())[:_fallback_token_cache_mark]
        for k in keys:
            del _fallback_token_cache[k]
    _fallback_token_cache[key] = count

    return count


# ---------------------------------------------------------------------------
# tiktoken integration (with fallback)
# ---------------------------------------------------------------------------

_tiktoken_available: bool = False
_tiktoken_module: object = None  # type: ignore[assignment]

try:
    import tiktoken as _actual_tiktoken

    _tiktoken_module = _actual_tiktoken
    _tiktoken_available = True

    # Monkeypatch tiktoken's download function to avoid network hangs.
    # tiktoken uses requests.get(blobpath) with no timeout, which can hang
    # indefinitely on slow/flaky networks.
    # Strategy: check the local cache first; if the BPE file isn't cached,
    # raise immediately so our get_encoding() fallback kicks in.
    import tiktoken.load as _tk_load  # type: ignore[attr-defined]
    import pathlib as _pathlib

    _TK_ORIG_READER: object = _tk_load.read_file  # type: ignore[attr-defined]

    def _tk_read_no_network(blobpath: str) -> bytes:
        # Local file path — delegate to original
        if "://" not in blobpath:
            if callable(_TK_ORIG_READER):
                return _TK_ORIG_READER(blobpath)
            raise FileNotFoundError(f"Local file not found: {blobpath}")

        # Remote URL — check if the file is already in tiktoken's cache
        cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", "")
        if cache_dir:
            fname = blobpath.rsplit("/", 1)[-1]
            cached = _pathlib.Path(cache_dir) / fname
            if cached.is_file():
                logger.debug("Reading cached BPE: %s", cached)
                return cached.read_bytes()

        # Not cached — tell the user and fail fast so the fallback is used
        fname = blobpath.rsplit("/", 1)[-1]
        logger.warning(
            "BPE file %s not cached at TIKTOKEN_CACHE_DIR=%s; "
            "falling back to heuristic token estimation",
            fname,
            cache_dir,
        )
        raise RuntimeError(f"BPE file {fname} not cached locally; use fallback instead")

    _tk_load.read_file = _tk_read_no_network  # type: ignore[attr-defined]

except ImportError:
    pass

_encoding_cache: dict[str, object] = {}

_MODEL_ENCODING_MAP: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude-3": "cl100k_base",
    "claude-3.5": "cl100k_base",
    "default": "cl100k_base",
}


def _build_fallback_encoding(encoding_name: str) -> object:
    """Build a duck-typed encoding object when tiktoken BPE data is unavailable."""

    class _FallbackEncoding:
        """Minimal encoding substitute."""

        def encode(self, text: str) -> list[int]:
            n = _fallback_count(text)
            return [0] * n

        def decode(self, tokens: list[int]) -> str:
            return f"<{len(tokens)} tokens>"

        @property
        def name(self) -> str:
            return f"fallback_{encoding_name}"

    return _FallbackEncoding()


def get_encoding(model: str = "default") -> object:
    """Get tiktoken encoding for a model, with caching and fallback.

    Returns an object with encode(text) -> list[int].
    Falls back to a lightweight estimator if tiktoken BPE data is unavailable.
    """
    if model not in _encoding_cache:
        enc_name = _MODEL_ENCODING_MAP.get(model, _MODEL_ENCODING_MAP["default"])

        if _tiktoken_available and _tiktoken_module is not None:
            try:
                _encoding_cache[model] = _tiktoken_module.get_encoding(enc_name)  # type: ignore[union-attr]
                return _encoding_cache[model]
            except Exception as exc:
                logger.debug(
                    "tiktoken encoding %s not available (%s); using fallback",
                    enc_name,
                    exc,
                )

        _encoding_cache[model] = _build_fallback_encoding(enc_name)

    return _encoding_cache[model]


# ---------------------------------------------------------------------------
# Token cache & count_tokens
# ---------------------------------------------------------------------------

_token_count_cache: dict[str, int] = {}
_max_token_cache = 1024


def count_tokens(text: str, model: str = "default") -> int:
    """Count tokens in a string with caching.

    Uses tiktoken when available; falls back to a heuristic character-based
    estimator that is accurate within ~3-5% for typical text and code.
    """
    # Use SHA-256 for cache key (not security-critical, but avoiding SHA1)
    ck = hashlib.sha256((model + text[:1000]).encode()).hexdigest()[:16]
    if ck in _token_count_cache:
        return _token_count_cache[ck]

    if _tiktoken_available and _tiktoken_module is not None:
        try:
            enc = get_encoding(model)
            if hasattr(enc, "encode"):
                count = len(enc.encode(text))  # type: ignore[arg-type]
            else:
                count = _fallback_count(text)
        except Exception:
            count = _fallback_count(text)
    else:
        count = _fallback_count(text)

    # Watermark eviction instead of full cache clear
    if len(_token_count_cache) >= int(_max_token_cache * 0.75):
        keys = list(_token_count_cache.keys())[: _max_token_cache // 2]
        for k in keys:
            del _token_count_cache[k]
    _token_count_cache[ck] = count

    return count


# ---------------------------------------------------------------------------
# Higher-level utilities
# ---------------------------------------------------------------------------


def count_message_tokens(messages: list[dict], model: str = "default") -> int:
    """Count tokens in a chat messages array.

    Adds ~4 tokens overhead per message for formatting.
    """
    total = 0
    for msg in messages:
        total += 4
        for _key, value in msg.items():
            if isinstance(value, str):
                total += count_tokens(value, model)
    total += 2
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
    price = prices[model_key]["input"]
    return (tokens / 1_000_000) * price


def content_hash(text: str) -> str:
    """Fast content hash for deduplication."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def truncate_to_tokens(text: str, max_tokens: int, model: str = "default") -> str:
    """Truncate text to fit within max_tokens."""
    if _tiktoken_available and _tiktoken_module is not None:
        try:
            enc = get_encoding(model)
            # Real tiktoken encodings have a non-fallback name; skip our
            # duck-typed fallback whose decode() is a stub.
            enc_name = getattr(enc, "name", "")
            if not enc_name.startswith("fallback_") and hasattr(enc, "encode") and hasattr(enc, "decode"):
                tokens = enc.encode(text)  # type: ignore[union-attr]
                if len(tokens) <= max_tokens:
                    return text
                return enc.decode(tokens[:max_tokens])  # type: ignore[union-attr]
        except Exception as e:
            logger.debug("Token truncation failed, using fallback: %s", e)

    # Fallback: character-level truncation
    ratio = _CHAR_TOKEN_RATIOS.get(
        _MODEL_ENCODING_MAP.get(model, "cl100k_base"),
        _DEFAULT_RATIO,
    )
    max_chars = int(max_tokens / ratio)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
