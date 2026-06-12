"""Tests for the budget guard."""

import time
import pytest

from tokensaver.budget import BudgetGuard, BudgetAction


@pytest.fixture
def tmp_budget(tmp_path):
    """Create a temporary budget guard."""
    db_path = str(tmp_path / "test_budget.db")
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budget_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            cost_usd REAL NOT NULL,
            day_start REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    guard = BudgetGuard.__new__(BudgetGuard)
    guard.daily_limit = 10.0
    guard.alert_threshold = 0.8
    guard.db_path = db_path
    return guard


def test_fresh_budget_is_pass(tmp_budget):
    status = tmp_budget.check()
    assert status.action == BudgetAction.PASS
    assert status.spent_today == 0.0
    assert status.remaining == 10.0
    assert status.utilization == 0.0


def test_recording_cost(tmp_budget):
    tmp_budget.record_cost(2.5)
    status = tmp_budget.check()
    assert status.spent_today == 2.5
    assert status.remaining == 7.5
    assert status.utilization == 0.25
    assert status.action == BudgetAction.PASS


def test_downgrade_at_80_percent(tmp_budget):
    tmp_budget.record_cost(8.5)  # 85%
    status = tmp_budget.check()
    assert status.action == BudgetAction.DOWNGRADE


def test_aggressive_compress_at_95_percent(tmp_budget):
    tmp_budget.record_cost(9.6)  # 96%
    status = tmp_budget.check()
    assert status.action == BudgetAction.AGGRESSIVE_COMPRESS


def test_block_at_100_percent(tmp_budget):
    tmp_budget.record_cost(10.5)  # 105%
    status = tmp_budget.check()
    assert status.action == BudgetAction.BLOCK


def test_block_when_would_exceed(tmp_budget):
    tmp_budget.record_cost(9.0)  # 90%
    status = tmp_budget.check(estimated_cost=2.0)  # would push to 110%
    assert status.action == BudgetAction.BLOCK


def test_set_daily_limit(tmp_budget):
    tmp_budget.set_daily_limit(50.0)
    assert tmp_budget.daily_limit == 50.0
    status = tmp_budget.check()
    assert status.daily_limit == 50.0
    assert status.remaining == 50.0


def test_multiple_costs(tmp_budget):
    for _ in range(10):
        tmp_budget.record_cost(0.5)  # $5 total = 50%
    status = tmp_budget.check()
    assert status.spent_today == 5.0
    assert status.action == BudgetAction.PASS  # 50% < 80%


def test_daily_breakdown(tmp_budget):
    tmp_budget.record_cost(1.0)
    tmp_budget.record_cost(2.0)
    breakdown = tmp_budget.get_daily_breakdown()
    assert breakdown["requests"] == 2
    assert breakdown["total_cost"] == 3.0
    assert breakdown["avg_cost"] == 1.5
    assert breakdown["max_cost"] == 2.0
