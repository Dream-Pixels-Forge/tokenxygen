"""Analytics and cost tracking for token usage."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

import logging

from tokenxygen.config import settings, today_start_timestamp
from tokenxygen.core import count_tokens, estimate_cost_usd

logger = logging.getLogger("tokenxygen.analytics")


@dataclass
class RequestRecord:
    timestamp: float
    model: str
    original_tokens: int
    optimized_tokens: int
    cache_hit: bool
    strategies_used: list[str]
    cost_before_usd: float
    cost_after_usd: float


class Analytics:
    """Track token usage, savings, and costs."""

    def __init__(self) -> None:
        self.db_path = settings.analytics.db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    model TEXT NOT NULL,
                    original_tokens INTEGER NOT NULL,
                    optimized_tokens INTEGER NOT NULL,
                    cache_hit BOOLEAN NOT NULL DEFAULT 0,
                    strategies_used TEXT,
                    cost_before_usd REAL NOT NULL,
                    cost_after_usd REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON requests(timestamp)
            """)
            conn.commit()

    def record(self, rec: RequestRecord) -> None:
        for attempt in range(3):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO requests
                        (timestamp, model, original_tokens, optimized_tokens, cache_hit,
                         strategies_used, cost_before_usd, cost_after_usd)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rec.timestamp,
                            rec.model,
                            rec.original_tokens,
                            rec.optimized_tokens,
                            rec.cache_hit,
                            ",".join(rec.strategies_used),
                            rec.cost_before_usd,
                            rec.cost_after_usd,
                        ),
                    )
                    conn.commit()
                return
            except sqlite3.OperationalError as e:
                logger.warning("Analytics record attempt %d failed: %s", attempt + 1, e)
                if attempt == 2:
                    return
                time.sleep(0.1 * (attempt + 1))

    def today_summary(self) -> dict:
        """Get today's usage summary."""
        today_start = today_start_timestamp()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as requests,
                    SUM(original_tokens) as total_original,
                    SUM(optimized_tokens) as total_optimized,
                    SUM(cost_before_usd) as cost_before,
                    SUM(cost_after_usd) as cost_after,
                    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits
                FROM requests
                WHERE timestamp >= ?
                """,
                (today_start,),
            ).fetchone()

            if row is None or row[0] == 0:
                return {
                    "requests": 0,
                    "original_tokens": 0,
                    "optimized_tokens": 0,
                    "saved_tokens": 0,
                    "cost_before_usd": 0.0,
                    "cost_after_usd": 0.0,
                    "saved_usd": 0.0,
                    "savings_pct": 0.0,
                    "cache_hits": 0,
                }

            requests, orig, opt, cost_before, cost_after, cache_hits = row
            saved = (orig or 0) - (opt or 0)
            savings_pct = (saved / orig * 100) if orig and orig > 0 else 0

            return {
                "requests": requests,
                "original_tokens": orig or 0,
                "optimized_tokens": opt or 0,
                "saved_tokens": saved,
                "cost_before_usd": cost_before or 0.0,
                "cost_after_usd": cost_after or 0.0,
                "saved_usd": (cost_before or 0) - (cost_after or 0),
                "savings_pct": round(savings_pct, 1),
                "cache_hits": cache_hits or 0,
            }

    def all_time_summary(self) -> dict:
        """Get all-time usage summary."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as requests,
                    SUM(original_tokens) as total_original,
                    SUM(optimized_tokens) as total_optimized,
                    SUM(cost_before_usd) as cost_before,
                    SUM(cost_after_usd) as cost_after,
                    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits
                FROM requests
                """
            ).fetchone()

            if row is None or row[0] == 0:
                return {"requests": 0, "saved_tokens": 0, "saved_usd": 0.0, "savings_pct": 0.0}

            requests, orig, opt, cost_before, cost_after, cache_hits = row
            saved = (orig or 0) - (opt or 0)
            savings_pct = (saved / orig * 100) if orig and orig > 0 else 0

            return {
                "requests": requests,
                "original_tokens": orig or 0,
                "optimized_tokens": opt or 0,
                "saved_tokens": saved,
                "cost_before_usd": cost_before or 0.0,
                "cost_after_usd": cost_after or 0.0,
                "saved_usd": (cost_before or 0) - (cost_after or 0),
                "savings_pct": round(savings_pct, 1),
                "cache_hits": cache_hits or 0,
            }

    def daily_costs(self, days: int = 30) -> list[dict]:
        """Get daily cost breakdown for last N days."""
        cutoff = time.time() - (days * 86400)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    date(timestamp, 'unixepoch') as day,
                    COUNT(*) as requests,
                    SUM(original_tokens) as original,
                    SUM(optimized_tokens) as optimized,
                    SUM(cost_before_usd) as cost_before,
                    SUM(cost_after_usd) as cost_after
                FROM requests
                WHERE timestamp >= ?
                GROUP BY day
                ORDER BY day
                """,
                (cutoff,),
            ).fetchall()

            return [
                {
                    "date": r[0],
                    "requests": r[1],
                    "original_tokens": r[2] or 0,
                    "optimized_tokens": r[3] or 0,
                    "saved_tokens": (r[2] or 0) - (r[3] or 0),
                    "cost_before_usd": r[4] or 0.0,
                    "cost_after_usd": r[5] or 0.0,
                }
                for r in rows
            ]





# Lazy singleton
def _get_analytics() -> Analytics:
    global analytics
    if "analytics" not in globals() or analytics is None:
        settings.ensure_dirs()
        analytics = Analytics()
    return analytics

# Module-level accessor
analytics = None  # type: ignore[assignment]
