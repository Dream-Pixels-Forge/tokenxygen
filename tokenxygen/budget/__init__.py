"""Budget guard — enforce daily spending limits with smart fallbacks.

When approaching the limit:
  1. 80% reached → downgrade to cheaper model
  2. 95% reached → aggressive compression + cheapest model
  3. 100% reached → block requests or use local fallback
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from tokenxygen.config import settings


class BudgetAction(Enum):
    PASS = "pass"                    # no action needed
    DOWNGRADE = "downgrade"          # use cheaper model
    AGGRESSIVE_COMPRESS = "compress" # maximum compression
    BLOCK = "block"                  # block the request


@dataclass
class BudgetStatus:
    daily_limit: float
    spent_today: float
    remaining: float
    utilization: float  # 0.0 to 1.0+
    action: BudgetAction
    reason: str


class BudgetGuard:
    """Track spending and enforce budget limits."""

    def __init__(self) -> None:
        self.daily_limit = settings.budget.daily_limit_usd
        self.alert_threshold = settings.budget.alert_threshold
        self.db_path = settings.analytics.db_path

    def check(self, estimated_cost: float = 0.0) -> BudgetStatus:
        """Check budget status and determine action.

        Args:
            estimated_cost: Cost of the upcoming request (if known).
        """
        spent = self._get_today_spent()
        remaining = max(0.0, self.daily_limit - spent)
        utilization = spent / self.daily_limit if self.daily_limit > 0 else 0.0

        # Determine action
        action, reason = self._decide(utilization, estimated_cost, remaining)

        return BudgetStatus(
            daily_limit=self.daily_limit,
            spent_today=spent,
            remaining=remaining,
            utilization=utilization,
            action=action,
            reason=reason,
        )

    def record_cost(self, cost_usd: float) -> None:
        """Record a cost to today's spending."""
        now = time.time()
        today_start = _today_start()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO budget_ledger (timestamp, cost_usd, day_start)
                VALUES (?, ?, ?)
                """,
                (now, cost_usd, today_start),
            )
            conn.commit()

    def get_daily_breakdown(self) -> dict:
        """Get detailed daily spending breakdown."""
        today_start = _today_start()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as requests,
                    SUM(cost_usd) as total_cost,
                    AVG(cost_usd) as avg_cost,
                    MAX(cost_usd) as max_cost
                FROM budget_ledger
                WHERE day_start = ?
                """,
                (today_start,),
            ).fetchone()

            if row is None or row[0] == 0:
                return {
                    "requests": 0,
                    "total_cost": 0.0,
                    "avg_cost": 0.0,
                    "max_cost": 0.0,
                }

            return {
                "requests": row[0],
                "total_cost": row[1] or 0.0,
                "avg_cost": row[2] or 0.0,
                "max_cost": row[3] or 0.0,
            }

    def _get_today_spent(self) -> float:
        """Get total amount spent today."""
        today_start = _today_start()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT SUM(cost_usd) FROM budget_ledger WHERE day_start = ?",
                (today_start,),
            ).fetchone()
            return row[0] if row and row[0] else 0.0

    def set_daily_limit(self, limit_usd: float) -> None:
        """Update the daily limit."""
        settings.budget.daily_limit_usd = limit_usd
        self.daily_limit = limit_usd

    def _decide(
        self, utilization: float, estimated_cost: float, remaining: float
    ) -> tuple[BudgetAction, str]:
        """Decide what action to take based on budget status."""
        # Block: over limit
        if utilization >= 1.0:
            return BudgetAction.BLOCK, f"budget_exhausted_{utilization:.0%}"

        # Would this request push us over?
        if estimated_cost > 0 and (utilization + estimated_cost / self.daily_limit) >= 1.0:
            return BudgetAction.BLOCK, f"would_exceed_limit"

        # Aggressive compress: >95%
        if utilization >= 0.95:
            return BudgetAction.AGGRESSIVE_COMPRESS, f"at_{utilization:.0%}_budget"

        # Downgrade: >80% (alert threshold)
        if utilization >= self.alert_threshold:
            return BudgetAction.DOWNGRADE, f"approaching_limit_{utilization:.0%}"

        return BudgetAction.PASS, "within_budget"


def _today_start() -> float:
    import datetime
    today = datetime.date.today()
    return datetime.datetime.combine(today, datetime.time.min).timestamp()


def _ensure_budget_table(db_path: str) -> None:
    """Create budget_ledger table if it doesn't exist."""
    import os
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budget_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                cost_usd REAL NOT NULL,
                day_start REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_budget_day
            ON budget_ledger(day_start)
        """)
        conn.commit()


# Lazy singleton
def _get_budget_guard() -> BudgetGuard:
    global budget_guard
    if "budget_guard" not in globals() or budget_guard is None:
        from tokenxygen.config import settings as _settings
        _ensure_budget_table(_settings.analytics.db_path)
        budget_guard = BudgetGuard()
    return budget_guard

budget_guard = None  # type: ignore[assignment]
