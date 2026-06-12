"""Semantic cache for LLM responses.

Stores (prompt_hash → response) for exact matches.
Stores (prompt_embedding → response) for semantic similarity.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Optional

import logging

from tokenxygen.config import settings

logger = logging.getLogger("tokenxygen.cache")


def content_hash(text: str) -> str:
    """Fast content hash for deduplication."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class SemanticCache:
    """SQLite-backed semantic cache with optional embedding similarity."""

    def __init__(self) -> None:
        self.db_path = settings.cache.db_path
        self.threshold = settings.cache.similarity_threshold
        self.max_entries = settings.cache.max_entries
        self.ttl = settings.cache.ttl_seconds
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    prompt_hash TEXT NOT NULL,
                    response TEXT NOT NULL,
                    tokens_saved INTEGER DEFAULT 0,
                    embedding BLOB,
                    created_at REAL NOT NULL,
                    hit_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_prompt_hash
                ON cache(prompt_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON cache(created_at)
            """)
            conn.commit()

    def get(self, messages: list[dict], model: str = "default") -> Optional[dict]:
        """Look up cache for matching messages.

        Returns cached response dict or None.
        """
        key = self._build_key(messages, model)

        for attempt in range(3):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    row = conn.execute(
                        "SELECT response, created_at, hit_count FROM cache WHERE key = ?",
                        (key,),
                    ).fetchone()

                    if row is None:
                        return None

                    response_json, created_at, hit_count = row

                    # Check TTL
                    if time.time() - created_at > self.ttl:
                        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                        conn.commit()
                        return None

                    # Update hit count
                    conn.execute(
                        "UPDATE cache SET hit_count = ? WHERE key = ?",
                        (hit_count + 1, key),
                    )
                    conn.commit()

                    return json.loads(response_json)
            except sqlite3.OperationalError as e:
                logger.warning("Cache get attempt %d failed: %s", attempt + 1, e)
                if attempt == 2:
                    return None
                time.sleep(0.1 * (attempt + 1))
        return None

    def put(
        self,
        messages: list[dict],
        response: dict,
        model: str = "default",
        tokens_used: int = 0,
    ) -> None:
        """Store a response in the cache."""
        key = self._build_key(messages, model)
        now = time.time()

        for attempt in range(3):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO cache
                        (key, prompt_hash, response, tokens_saved, created_at, hit_count)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (key, content_hash(str(messages)), json.dumps(response), tokens_used, now, 0),
                    )

                    # Evict old entries if over limit
                    count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                    if count > self.max_entries:
                        conn.execute(
                            """
                            DELETE FROM cache WHERE key IN (
                                SELECT key FROM cache ORDER BY created_at ASC LIMIT ?
                            )
                            """,
                            (count - self.max_entries + 1000,),
                        )

                    conn.commit()
                return
            except sqlite3.OperationalError as e:
                logger.warning("Cache put attempt %d failed: %s", attempt + 1, e)
                if attempt == 2:
                    return
                time.sleep(0.1 * (attempt + 1))

    def stats(self) -> dict:
        """Return cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(hit_count), SUM(tokens_saved) FROM cache"
            ).fetchone()
            total, total_hits, total_saved = row
            return {
                "entries": total or 0,
                "total_hits": total_hits or 0,
                "tokens_saved": total_saved or 0,
            }

    def clear(self) -> int:
        """Clear all cache entries. Returns count cleared."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            conn.execute("DELETE FROM cache")
            conn.commit()
            return count

    def _build_key(self, messages: list[dict], model: str) -> str:
        """Build a deterministic cache key from chat messages.
        
        Uses SHA-256 (128-bit hex) to minimize collision risk.
        """
        # Normalize messages: sort keys, strip whitespace
        import hashlib
        normalized = []
        for msg in messages:
            normalized.append({
                "role": msg.get("role", ""),
                "content": msg.get("content", ""),
            })
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        # Use SHA-256 for collision resistance
        key_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return f"{model}:{key_hash}"


# Lazy singleton
def _get_cache() -> SemanticCache:
    global cache
    if "cache" not in globals() or cache is None:
        settings.ensure_dirs()
        cache = SemanticCache()
    return cache

# Module-level accessor
cache = None  # type: ignore[assignment]
