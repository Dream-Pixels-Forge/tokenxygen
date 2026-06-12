"""Tests for the analytics module."""

import tempfile
import time

import pytest

from tokensaver.analytics import Analytics, RequestRecord


@pytest.fixture
def tmp_analytics(tmp_path):
    """Create a temporary analytics instance."""
    db_path = str(tmp_path / "test_analytics.db")
    a = Analytics.__new__(Analytics)
    a.db_path = db_path
    a._init_db()
    return a


def test_record_and_summary(tmp_analytics):
    tmp_analytics.record(
        RequestRecord(
            timestamp=time.time(),
            model="gpt-4o",
            original_tokens=1000,
            optimized_tokens=600,
            cache_hit=False,
            strategies_used=["file_dedup", "comment_strip"],
            cost_before_usd=0.0025,
            cost_after_usd=0.0015,
        )
    )

    summary = tmp_analytics.today_summary()
    assert summary["requests"] == 1
    assert summary["original_tokens"] == 1000
    assert summary["optimized_tokens"] == 600
    assert summary["saved_tokens"] == 400
    assert summary["savings_pct"] == 40.0
    assert summary["saved_usd"] > 0


def test_empty_summary(tmp_analytics):
    summary = tmp_analytics.today_summary()
    assert summary["requests"] == 0
    assert summary["saved_tokens"] == 0


def test_multiple_records(tmp_analytics):
    for i in range(5):
        tmp_analytics.record(
            RequestRecord(
                timestamp=time.time(),
                model="gpt-4o",
                original_tokens=1000,
                optimized_tokens=800,
                cache_hit=i == 2,
                strategies_used=["file_dedup"],
                cost_before_usd=0.0025,
                cost_after_usd=0.0020,
            )
        )

    summary = tmp_analytics.today_summary()
    assert summary["requests"] == 5
    assert summary["original_tokens"] == 5000
    assert summary["saved_tokens"] == 1000
    assert summary["cache_hits"] == 1
