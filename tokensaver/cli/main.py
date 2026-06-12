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
def serve(host: str, port: int, upstream: str | None):
    """Start the TokenSaver proxy server."""
    from tokensaver.config import settings

    if upstream:
        settings.proxy.upstream_base_url = upstream

    settings.ensure_dirs()

    console.print(
        Panel(
            f"[bold green]TokenSaver Proxy[/]\n\n"
            f"  Listening:  [cyan]http://{host}:{port}[/]\n"
            f"  Upstream:   [dim]{settings.proxy.upstream_base_url}[/]\n"
            f"  Cache:      {'[green]ON' if settings.cache.enabled else '[red]OFF'}[/]\n"
            f"  Compress:   {'[green]ON' if settings.compress.enabled else '[red]OFF'}[/]\n"
            f"  Router:     {'[green]ON' if settings.router.enabled else '[red]OFF'}[/]\n\n"
            f"  [dim]Set OPENAI_BASE_URL=http://{host}:{port}/v1 to use with any tool[/]",
            title="🚀 TokenSaver",
            border_style="green",
        )
    )

    import uvicorn
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
    from tokensaver.cache import _get_cache

    analytics = _get_analytics()
    cache = _get_cache()
    today = analytics.today_summary()
    alltime = analytics.all_time_summary()
    cache_info = cache.stats()

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
    console.print(
        Panel(
            "[bold]🔧 Setup Instructions[/]\n\n"
            "[bold cyan]Claude Code:[/]\n"
            "  export OPENAI_BASE_URL=http://127.0.0.1:8420/v1\n"
            "  export OPENAI_API_KEY=your-key-here\n"
            "  claude  # start normally\n\n"
            "[bold cyan]Cursor:[/]\n"
            "  Settings → Models → Override OpenAI Base URL\n"
            "  Set to: http://127.0.0.1:8420/v1\n\n"
            "[bold cyan]Windsurf:[/]\n"
            "  export OPENAI_BASE_URL=http://127.0.0.1:8420/v1\n"
            "  windsurf  # start normally\n\n"
            "[bold cyan]Any Python/OpenAI app:[/]\n"
            "  client = OpenAI(base_url='http://127.0.0.1:8420/v1')\n\n"
            "[bold cyan]Shell (all tools):[/]\n"
            "  eval \"$(tokensaver env)\"",
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
@click.option("--clear-cache", is_flag=True, help="Also clear the cache")
def reset(clear_cache: bool):
    """Reset all analytics data."""
    from tokensaver.analytics import _get_analytics
    from tokensaver.cache import _get_cache

    import os
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


if __name__ == "__main__":
    cli()
