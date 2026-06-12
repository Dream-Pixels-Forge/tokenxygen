"""Tokenxygen CLI — manage the optimizer, view stats, control the proxy."""

from __future__ import annotations


import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


@click.group()
@click.version_option(package_name="tokenxygen")
def cli():
    """Tokenxygen — Universal token optimizer for coding agents."""
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8420, type=int, help="Bind port")
@click.option("--upstream", default=None, help="Override upstream API base URL")
@click.option("--dashboard-port", default=8421, type=int, help="Dashboard port (0 to disable)")
@click.option("--json-logs", is_flag=True, help="Use JSON log format")
@click.option("--log-level", default="INFO", help="Log level")
def serve(host: str, port: int, upstream: str | None, dashboard_port: int, json_logs: bool, log_level: str):
    """Start the Tokenxygen proxy server."""
    from tokenxygen.config import settings

    if upstream:
        settings.proxy.upstream_base_url = upstream

    settings.ensure_dirs()

    # Setup logging
    from tokenxygen.logging import setup_logging
    setup_logging(level=log_level, json_format=json_logs)

    console.print(
        Panel(
            f"[bold green]Tokenxygen Proxy[/]\n\n"
            f"  Proxy:      [cyan]http://{host}:{port}[/]\n"
            f"  Dashboard:  [cyan]http://{host}:{dashboard_port}[/]\n"
            f"  Upstream:   [dim]{settings.proxy.upstream_base_url}[/]\n\n"
            f"  Cache:      {'[green]ON' if settings.cache.enabled else '[red]OFF'}[/]\n"
            f"  Compress:   {'[green]ON' if settings.compress.enabled else '[red]OFF'}[/]\n"
            f"  Router:     {'[green]ON' if settings.router.enabled else '[red]OFF'}[/]\n"
            f"  Budget:     [cyan]${settings.budget.daily_limit_usd}/day[/]\n\n"
            f"  [dim]Set OPENAI_BASE_URL=http://{host}:{port}/v1 to use with any tool[/]",
            title="🚀 Tokenxygen v0.2",
            border_style="green",
        )
    )

    import multiprocessing
    import uvicorn

    def run_dashboard():
        if dashboard_port > 0:
            from tokenxygen.dashboard import dashboard_app
            uvicorn.run(dashboard_app, host=host, port=dashboard_port, log_level="warning")

    # Start dashboard in background
    if dashboard_port > 0:
        p = multiprocessing.Process(target=run_dashboard, daemon=True)
        p.start()

    uvicorn.run(
        "tokenxygen.core.proxy:app",
        host=host,
        port=port,
        log_level="info",
    )


@cli.command()
def stats():
    """Show token usage statistics."""
    from tokenxygen.analytics import _get_analytics
    from tokenxygen.budget import _get_budget_guard
    from tokenxygen.cache import _get_cache

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
    from tokenxygen.analytics import _get_analytics

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
    from tokenxygen.config import settings

    host = settings.proxy.host
    port = settings.proxy.port
    dash_port = 8421

    console.print(
        Panel(
            "[bold]🔧 Setup Instructions[/]\n\n"
            "[bold cyan]1. Start the proxy:[/]\n"
            "  tokenxygen serve\n\n"
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
            "    eval \"$(tokenxygen env)\"\n\n"
            "[bold cyan]3. View dashboard:[/]\n"
            f"  Open http://{host}:{dash_port} in your browser\n\n"
            "[bold cyan]4. Check savings:[/]\n"
            "  tokenxygen stats",
            title="🚀 Getting Started",
            border_style="cyan",
        )
    )


@cli.command()
def env():
    """Print shell exports to enable Tokenxygen for all tools."""
    from tokenxygen.config import settings

    host = settings.proxy.host
    port = settings.proxy.port
    print(f"export OPENAI_BASE_URL=http://{host}:{port}/v1")
    print(f"export TOKENDATA_DIR={settings.cache.db_path.rsplit('/', 1)[0]}")


@cli.command()
@click.argument("limit_usd", type=float)
def budget(limit_usd: float):
    """Set the daily budget limit in USD."""
    from tokenxygen.budget import _get_budget_guard

    guard = _get_budget_guard()
    guard.set_daily_limit(limit_usd)
    console.print(f"[green]✓ Daily budget set to ${limit_usd:.2f}[/]")


@cli.command()
def budget_status():
    """Show current budget status."""
    from tokenxygen.budget import _get_budget_guard

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
    from tokenxygen.cache import _get_cache

    import os
    from tokenxygen.config import settings
    os.remove(settings.analytics.db_path)

    if clear_cache:
        _get_cache().clear()

    console.print("[green]✓ Analytics data reset.[/]")


@cli.command()
@click.argument("prompt")
@click.option("--model", default="gpt-4o", help="Model to estimate for")
def tokens(prompt: str, model: str):
    """Count tokens in a text string."""
    from tokenxygen.core import count_tokens, estimate_cost_usd

    token_count = count_tokens(prompt, model)
    cost = estimate_cost_usd(token_count, model)

    console.print(f"Tokens: [bold cyan]{token_count}[/]")
    console.print(f"Est. cost ({model}): [green]${cost:.6f}[/]")


@cli.command()
@click.argument("text")
def compress(text: str):
    """Show compression results for a text string."""
    from tokenxygen.compress import PromptCompressor
    from tokenxygen.core import count_tokens

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


@cli.command()
def providers():
    """List available models and providers."""
    from tokenxygen.providers import MODEL_REGISTRY

    table = Table(title="🔌 Available Models", box=box.ROUNDED)
    table.add_column("Model", style="cyan")
    table.add_column("Provider", style="purple")
    table.add_column("Input $/1K", justify="right")
    table.add_column("Output $/1K", justify="right")
    table.add_column("Context", justify="right")

    for name, config in sorted(MODEL_REGISTRY.items()):
        table.add_row(
            name,
            config.provider.value,
            f"${config.cost_per_1k_input:.3f}",
            f"${config.cost_per_1k_output:.3f}",
            f"{config.max_context // 1000}K",
        )

    console.print(table)


@cli.command()
def plugins():
    """List loaded compression plugins."""
    from tokenxygen.plugins import registry

    strategies = registry.get_all()

    if not strategies:
        console.print("[dim]No plugins loaded.[/]")
        return

    table = Table(title="🧩 Compression Plugins", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Priority", justify="right")
    table.add_column("Description")

    for s in strategies:
        table.add_row(s.name, str(s.priority), s.description)

    console.print(table)


@cli.command()
@click.argument("model_a")
@click.argument("model_b")
@click.option("--tokens", "token_count", default=1000, type=int, help="Token count to compare")
def compare(model_a: str, model_b: str, token_count: int):
    """Compare cost between two models."""
    from tokenxygen.providers import MODEL_REGISTRY

    a = MODEL_REGISTRY.get(model_a)
    b = MODEL_REGISTRY.get(model_b)

    if not a:
        console.print(f"[red]Unknown model: {model_a}[/]")
        return
    if not b:
        console.print(f"[red]Unknown model: {model_b}[/]")
        return

    cost_a = a.cost_per_token_input * token_count
    cost_b = b.cost_per_token_input * token_count

    cheaper = model_a if cost_a < cost_b else model_b
    savings = abs(cost_a - cost_b)

    table = Table(title=f"💰 Cost Comparison ({token_count:,} tokens)", box=box.ROUNDED)
    table.add_column("Model", style="cyan")
    table.add_column("Provider")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("")

    table.add_row(model_a, a.provider.value, f"${cost_a:.6f}", "← CHEAPER" if cheaper == model_a else "")
    table.add_row(model_b, b.provider.value, f"${cost_b:.6f}", "← CHEAPER" if cheaper == model_b else "")
    table.add_row("", "", "", "")
    table.add_row("Savings", "", f"${savings:.6f}", f"{((savings / max(cost_a, cost_b)) * 100):.1f}%" if max(cost_a, cost_b) > 0 else "")

    console.print(table)


@cli.command()
def cheapest():
    """Show cheapest model for common token counts."""
    from tokenxygen.providers import get_cheapest_provider

    console.print("[bold]💸 Cheapest Models by Context Size[/]\n")

    table = Table(box=box.ROUNDED)
    table.add_column("Tokens", style="cyan", justify="right")
    table.add_column("Best Model", style="green")
    table.add_column("Provider")
    table.add_column("Cost", justify="right")

    for token_count in [100, 500, 1000, 2000, 5000, 10000, 50000]:
        provider, model, cost = get_cheapest_provider(token_count)
        table.add_row(
            f"{token_count:,}",
            model,
            provider.value,
            f"${cost:.6f}",
        )

    console.print(table)


@cli.command()
def cache_stats():
    """Show detailed cache statistics."""
    from tokenxygen.cache import _get_cache
    from tokenxygen.config import settings as _settings

    cache = _get_cache()
    stats = cache.stats()

    console.print(
        Panel(
            f"[bold]Entries:[/]     {stats['entries']:,}\n"
            f"[bold]Total Hits:[/]  {stats['total_hits']:,}\n"
            f"[bold]Tokens Saved:[/] {stats['tokens_saved']:,}\n\n"
            f"[dim]Cache TTL: {_settings.cache.ttl_seconds // 3600}h | "
            f"Max: {_settings.cache.max_entries:,} entries | "
            f"Threshold: {_settings.cache.similarity_threshold}[/]",
            title="💾 Cache Statistics",
            border_style="cyan",
        )
    )


@cli.command()
def failover():
    """Show failover pool status."""
    from tokenxygen.providers.failover import get_pool

    pool = get_pool()
    stats = pool.get_stats()

    table = Table(title="🔄 Failover Pool", box=box.ROUNDED)
    table.add_column("Provider", style="cyan")
    table.add_column("Status")
    table.add_column("Requests", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Failure Rate", justify="right")

    for provider, data in stats.items():
        status = "[green]✓ UP[/]" if data["available"] else "[red]✗ DOWN[/]"
        fail_rate = f"{data['failure_rate']:.1%}"
        table.add_row(
            provider,
            status,
            str(data["total_requests"]),
            str(data["total_failures"]),
            f"{data['avg_latency_ms']:.0f}ms",
            fail_rate,
        )

    console.print(table)


@cli.command()
@click.argument("text")
def deep_compress(text: str):
    """Show advanced LLMLingua-2 compression results."""
    from tokenxygen.compress.advanced import llmlingua

    compressed, stats = llmlingua.compress(text, compression_ratio=0.5)

    console.print(f"Method:     [cyan]{stats.method}[/]")
    console.print(f"Original:   [dim]{stats.original_tokens} tokens[/]")
    console.print(f"Compressed: [green]{stats.compressed_tokens} tokens[/]")
    console.print(f"Saved:      [bold green]{stats.tokens_removed} tokens ({stats.savings_pct:.1f}%)[/]")
    console.print("\n[dim]Compressed text:[/]")
    console.print(compressed[:500] + ("..." if len(compressed) > 500 else ""))


@cli.command()
def metrics_cmd():
    """Show current metrics."""
    from tokenxygen.metrics import metrics

    data = metrics.to_dict()

    console.print("[bold]📊 Metrics[/]\n")

    # Counters
    counters_table = Table(title="Counters", box=box.ROUNDED)
    counters_table.add_column("Metric", style="cyan")
    counters_table.add_column("Value", justify="right", style="green")

    for name, value in sorted(data.get("counters", {}).items()):
        counters_table.add_row(name, str(int(value)))

    console.print(counters_table)
    console.print()

    # Histograms
    hist_table = Table(title="Histograms", box=box.ROUNDED)
    hist_table.add_column("Metric", style="cyan")
    hist_table.add_column("Count", justify="right")
    hist_table.add_column("Total", justify="right")
    hist_table.add_column("Avg", justify="right", style="green")

    for name, hist in sorted(data.get("histograms", {}).items()):
        hist_table.add_row(
            name,
            str(hist["count"]),
            f"{hist['total']:.2f}",
            f"{hist['avg']:.2f}",
        )

    console.print(hist_table)


if __name__ == "__main__":
    cli()
