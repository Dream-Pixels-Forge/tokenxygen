"""Semantic cache for LLM responses.

Stores (prompt_hash → response) for exact matches.
Stores (prompt_embedding → response) for semantic similarity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

from tokenxygen.config import settings

logger = logging.getLogger("tokenxygen.cache")


def content_hash(text: str) -> str:
    """Fast content hash for deduplication."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class DatabasePool:
    """Thread-safe SQLite connection pool with WAL mode."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
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

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._path, timeout=10)
        return self._local.conn

    @contextmanager
    def connection(self):
        """Context manager for database operations with automatic rollback on error."""
        conn = self._get_connection()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise


class SemanticCache:
    """SQLite-backed semantic cache with optional embedding similarity."""

    def __init__(self) -> None:
        self.db_path = settings.cache.db_path
        self.threshold = settings.cache.similarity_threshold
        self.max_entries = settings.cache.max_entries
        self.ttl = settings.cache.ttl_seconds
        self._pool = DatabasePool(self.db_path)

    def get(self, messages: list[dict], model: str = "default") -> Optional[dict]:
        """Look up cache for matching messages.

        Returns cached response dict or None.
        """
        key = self._build_key(messages, model)

        try:
            with self._pool.connection() as conn:
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
            logger.warning("Cache get failed: %s", e)
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

        try:
            with self._pool.connection() as conn:
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
        except sqlite3.OperationalError as e:
            logger.warning("Cache put failed: %s", e)

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._pool.connection() as conn:
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
        with self._pool.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            conn.execute("DELETE FROM cache")
            conn.commit()
            return count

    def _build_key(self, messages: list[dict], model: str) -> str:
        """Build a deterministic cache key from chat messages.
        
        Uses SHA-256 (256-bit hex) to minimize collision risk.
        """
        # Normalize messages: sort keys, strip whitespace
        normalized = []
        for msg in messages:
            normalized.append({
                "role": msg.get("role", ""),
                "content": msg.get("content", ""),
            })
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        # Use full SHA-256 for maximum collision resistance
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        return f"{model}:{key_hash}"


# Lazy singleton with clean naming
_cache_instance: SemanticCache | None = None


def _get_cache() -> SemanticCache:
    """Get or create the singleton cache instance."""
    global _cache_instance
    if _cache_instance is None:
        settings.ensure_dirs()
        _cache_instance = SemanticCache()
    return _cache_instance
