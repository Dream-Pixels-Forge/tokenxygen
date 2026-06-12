"""TokenSaver CLI — manage the optimizer, view stats, control the proxy."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


@click.group()
@click.version_option(package_name="tokensaver")
def cli():
    """TokenSaver — Universal token optimizer for coding agents."""
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8420, type=int, help="Bind port")
@click.option("--upstream", default=None, help="Override upstream API base URL")
@click.option("--dashboard-port", default=8421, type=int, help="Dashboard port (0 to disable)")
def serve(host: str, port: int, upstream: str | None, dashboard_port: int):
    """Start the TokenSaver proxy server."""
    from tokensaver.config import settings

    if upstream:
        settings.proxy.upstream_base_url = upstream

    settings.ensure_dirs()

    console.print(
        Panel(
            f"[bold green]TokenSaver Proxy[/]\n\n"
            f"  Proxy:      [cyan]http://{host}:{port}[/]\n"
            f"  Dashboard:  [cyan]http://{host}:{dashboard_port}[/]\n"
            f"  Upstream:   [dim]{settings.proxy.upstream_base_url}[/]\n\n"
            f"  Cache:      {'[green]ON' if settings.cache.enabled else '[red]OFF'}[/]\n"
            f"  Compress:   {'[green]ON' if settings.compress.enabled else '[red]OFF'}[/]\n"
            f"  Router:     {'[green]ON' if settings.router.enabled else '[red]OFF'}[/]\n"
            f"  Budget:     [cyan]${settings.budget.daily_limit_usd}/day[/]\n\n"
            f"  [dim]Set OPENAI_BASE_URL=http://{host}:{port}/v1 to use with any tool[/]",
            title="🚀 TokenSaver v0.2",
            border_style="green",
        )
    )

    import multiprocessing
    import uvicorn

    def run_dashboard():
        if dashboard_port > 0:
            from tokensaver.dashboard import dashboard_app
            uvicorn.run(dashboard_app, host=host, port=dashboard_port, log_level="warning")

    # Start dashboard in background
    if dashboard_port > 0:
        p = multiprocessing.Process(target=run_dashboard, daemon=True)
        p.start()

    uvicorn.run(
        "tokensaver.core.proxy:app",
        host=host,
        port=port,
        log_level="info",
    )


@cli.command()
def stats():
    """Show token usage statistics."""
    from tokensaver.analytics import _get_analytics
    from tokensaver.budget import _get_budget_guard
    from tokensaver.cache import _get_cache

    analytics = _get_analytics()
    cache = _get_cache()

    today = analytics.today_summary()
    alltime = analytics.all_time_summary()
    cache_info = cache.stats()
    budget = _get_budget_guard().check()

    # Today
    table = Table(title="📊 Today's Usage", box=box.ROUNDED, show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Requests", str(today["requests"]))
    table.add_row("Original Tokens", f"{today['original_tokens']:,}")
    table.add_row("Optimized Tokens", f"{today['optimized_tokens']:,}")
    table.add_row("Saved Tokens", f"[bold]{today['saved_tokens']:,}[/]")
    table.add_row("Savings", f"[bold]{today['savings_pct']}%[/]")
    table.add_row("Cost (Before)", f"${today['cost_before_usd']:.4f}")
    table.add_row("Cost (After)", f"${today['cost_after_usd']:.4f}")
    table.add_row("Money Saved", f"[bold green]${today['saved_usd']:.4f}[/]")
    table.add_row("Cache Hits", str(today["cache_hits"]))

    console.print(table)
    console.print()

    # All-time
    table2 = Table(title="📈 All-Time", box=box.ROUNDED)
    table2.add_column("Metric", style="cyan")
    table2.add_column("Value", style="green", justify="right")

    table2.add_row("Total Requests", str(alltime.get("requests", 0)))
    table2.add_row("Total Saved Tokens", f"{alltime.get('saved_tokens', 0):,}")
    table2.add_row("Total Money Saved", f"[bold green]${alltime.get('saved_usd', 0):.4f}[/]")
    table2.add_row("Overall Savings", f"{alltime.get('savings_pct', 0)}%")

    console.print(table2)
    console.print()

    # Budget
    budget_table = Table(title="🛡️ Budget", box=box.ROUNDED)
    budget_table.add_column("Metric", style="cyan")
    budget_table.add_column("Value", style="green", justify="right")

    budget_table.add_row("Daily Limit", f"${budget.daily_limit:.2f}")
    budget_table.add_row("Spent Today", f"${budget.spent_today:.4f}")
    budget_table.add_row("Remaining", f"[bold]${budget.remaining:.4f}[/]")
    budget_table.add_row("Utilization", f"{budget.utilization:.1%}")
    budget_table.add_row("Action", budget.action.value.upper())

    console.print(budget_table)
    console.print()

    # Cache
    cache_table = Table(title="💾 Cache", box=box.ROUNDED)
    cache_table.add_column("Metric", style="cyan")
    cache_table.add_column("Value", style="green", justify="right")

    cache_table.add_row("Entries", str(cache_info["entries"]))
    cache_table.add_row("Total Hits", str(cache_info["total_hits"]))
    cache_table.add_row("Tokens Saved (Cache)", f"{cache_info['tokens_saved']:,}")

    console.print(cache_table)


@cli.command()
@click.option("--days", default=30, type=int, help="Number of days to show")
def history(days: int):
    """Show daily cost history."""
    from tokensaver.analytics import _get_analytics

    daily = _get_analytics().daily_costs(days)

    if not daily:
        console.print("[dim]No data yet. Start the proxy and make some requests![/]")
        return

    table = Table(title=f"📅 Daily Costs (Last {days} Days)", box=box.ROUNDED)
    table.add_column("Date", style="cyan")
    table.add_column("Requests", justify="right")
    table.add_column("Original", justify="right")
    table.add_column("Optimized", justify="right")
    table.add_column("Saved", justify="right", style="green")
    table.add_column("Cost Before", justify="right")
    table.add_column("Cost After", justify="right", style="green")

    for day in daily:
        table.add_row(
            day["date"],
            str(day["requests"]),
            f"{day['original_tokens']:,}",
            f"{day['optimized_tokens']:,}",
            f"{day['saved_tokens']:,}",
            f"${day['cost_before_usd']:.4f}",
            f"${day['cost_after_usd']:.4f}",
        )

    console.print(table)


@cli.command()
def setup():
    """Show setup instructions for popular coding agents."""
    from tokensaver.config import settings

    host = settings.proxy.host
    port = settings.proxy.port
    dash_port = 8421

    console.print(
        Panel(
            "[bold]🔧 Setup Instructions[/]\n\n"
            "[bold cyan]1. Start the proxy:[/]\n"
            "  tokensaver serve\n\n"
            "[bold cyan]2. Point your tool to the proxy:[/]\n\n"
            "  [bold]Claude Code:[/]\n"
            f"    export OPENAI_BASE_URL=http://{host}:{port}/v1\n"
            "    claude\n\n"
            "  [bold]Cursor:[/]\n"
            f"    Settings → Models → Override OpenAI Base URL → http://{host}:{port}/v1\n\n"
            "  [bold]Windsurf:[/]\n"
            f"    export OPENAI_BASE_URL=http://{host}:{port}/v1\n"
            "    windsurf\n\n"
            "  [bold]Python/OpenAI SDK:[/]\n"
            f"    client = OpenAI(base_url='http://{host}:{port}/v1')\n\n"
            "  [bold]Shell (all tools):[/]\n"
            "    eval \"$(tokensaver env)\"\n\n"
            "[bold cyan]3. View dashboard:[/]\n"
            f"  Open http://{host}:{dash_port} in your browser\n\n"
            "[bold cyan]4. Check savings:[/]\n"
            "  tokensaver stats",
            title="🚀 Getting Started",
            border_style="cyan",
        )
    )


@cli.command()
def env():
    """Print shell exports to enable TokenSaver for all tools."""
    from tokensaver.config import settings

    host = settings.proxy.host
    port = settings.proxy.port
    print(f"export OPENAI_BASE_URL=http://{host}:{port}/v1")
    print(f"export TOKENDATA_DIR={settings.cache.db_path.rsplit('/', 1)[0]}")


@cli.command()
@click.argument("limit_usd", type=float)
def budget(limit_usd: float):
    """Set the daily budget limit in USD."""
    from tokensaver.budget import _get_budget_guard

    guard = _get_budget_guard()
    guard.set_daily_limit(limit_usd)
    console.print(f"[green]✓ Daily budget set to ${limit_usd:.2f}[/]")


@cli.command()
def budget_status():
    """Show current budget status."""
    from tokensaver.budget import _get_budget_guard

    b = _get_budget_guard().check()

    color = "green" if b.utilization < 0.8 else "orange" if b.utilization < 0.95 else "red"

    console.print(
        Panel(
            f"[{color}]${b.spent_today:.4f}[/] spent of [cyan]${b.daily_limit:.2f}[/]\n"
            f"Remaining: [bold {color}]${b.remaining:.4f}[/]\n"
            f"Utilization: [{color}]{b.utilization:.1%}[/]\n"
            f"Action: [bold]{b.action.value.upper()}[/]",
            title="🛡️ Budget Status",
            border_style=color,
        )
    )


@cli.command()
@click.option("--clear-cache", is_flag=True, help="Also clear the cache")
def reset(clear_cache: bool):
    """Reset all analytics data."""
    from tokensaver.cache import _get_cache

    import os
    from tokensaver.config import settings
    os.remove(settings.analytics.db_path)

    if clear_cache:
        _get_cache().clear()

    console.print("[green]✓ Analytics data reset.[/]")


@cli.command()
@click.argument("prompt")
@click.option("--model", default="gpt-4o", help="Model to estimate for")
def tokens(prompt: str, model: str):
    """Count tokens in a text string."""
    from tokensaver.core import count_tokens, estimate_cost_usd

    token_count = count_tokens(prompt, model)
    cost = estimate_cost_usd(token_count, model)

    console.print(f"Tokens: [bold cyan]{token_count}[/]")
    console.print(f"Est. cost ({model}): [green]${cost:.6f}[/]")


@cli.command()
@click.argument("text")
def compress(text: str):
    """Show compression results for a text string."""
    from tokensaver.compress import PromptCompressor
    from tokensaver.core import count_tokens

    messages = [{"role": "user", "content": text}]
    c = PromptCompressor(aggressiveness=0.5)
    compressed, results = c.compress(messages, "gpt-4o")

    original = count_tokens(text, "gpt-4o")
    optimized = count_tokens(compressed[0]["content"], "gpt-4o") if compressed else 0

    console.print(f"Original:   [dim]{original} tokens[/]")
    console.print(f"Compressed: [green]{optimized} tokens[/]")
    console.print(f"Saved:      [bold green]{original - optimized} tokens ({((original - optimized) / original * 100) if original else 0:.1f}%)[/]")

    if results:
        console.print("\n[bold]Strategies applied:[/]")
        for r in results:
            console.print(f"  • {r.strategy}: {r.saved_tokens} tokens saved")


if __name__ == "__main__":
    cli()
