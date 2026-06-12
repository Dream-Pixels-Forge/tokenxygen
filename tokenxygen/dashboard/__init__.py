"""Web dashboard for Tokenxygen — real-time stats, charts, and controls."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

DASHBOARD_HTML = Path(__file__).parent / "index.html"


def _read_dashboard_html() -> str:
    """Read dashboard HTML with error handling."""
    try:
        return DASHBOARD_HTML.read_text()
    except FileNotFoundError:
        return """<!DOCTYPE html><html><body><h1>Dashboard</h1><p>Dashboard HTML file not found.</p></body></html>"""

dashboard_app = FastAPI(title="Tokenxygen Dashboard")


@dashboard_app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard SPA."""
    return _read_dashboard_html()


@dashboard_app.get("/api/stats")
async def api_stats():
    """Proxy stats endpoint for the dashboard."""
    from tokenxygen.analytics import _get_analytics
    from tokenxygen.budget import _get_budget_guard
    from tokenxygen.cache import _get_cache
    from tokenxygen.config import settings

    return {
        "today": _get_analytics().today_summary(),
        "all_time": _get_analytics().all_time_summary(),
        "cache": _get_cache().stats(),
        "budget": {
            "daily_limit": settings.budget.daily_limit_usd,
            "breakdown": _get_budget_guard().get_daily_breakdown(),
        },
    }


@dashboard_app.get("/api/history")
async def api_history(days: int = 30):
    """Daily cost history."""
    from tokenxygen.analytics import _get_analytics
    return _get_analytics().daily_costs(days)


@dashboard_app.get("/api/budget")
async def api_budget():
    """Budget status."""
    from tokenxygen.budget import _get_budget_guard
    from tokenxygen.config import settings

    budget = _get_budget_guard().check()
    return {
        "daily_limit": budget.daily_limit,
        "spent_today": budget.spent_today,
        "remaining": budget.remaining,
        "utilization": round(budget.utilization, 4),
        "action": budget.action.value,
    }
