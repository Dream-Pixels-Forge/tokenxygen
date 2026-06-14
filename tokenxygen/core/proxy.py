"""Tokenxygen proxy server — OpenAI-compatible API that optimizes tokens in-flight."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from tokenxygen.analytics import RequestRecord, _get_analytics
from tokenxygen.budget import BudgetAction, _get_budget_guard
from tokenxygen.cache import _get_cache
from tokenxygen.compress import PromptCompressor, compressor
from tokenxygen.config import settings
from tokenxygen.core import count_tokens, estimate_cost_usd
from tokenxygen.metrics import metrics
from tokenxygen.router import router

# Thread-safe in-memory rate limiter
import threading
_rate_limit_lock = threading.Lock()
_rate_limit_store: dict[str, list[float]] = {}

_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

logger = logging.getLogger("tokenxygen")

# Shared HTTP client for upstream requests
_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — manages startup/shutdown."""
    global _client, _rate_limit_store
    _rate_limit_store = {}
    yield
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None

app = FastAPI(
    title="Tokenxygen",
    description="Universal token optimizer for coding agents — save 40-70% on LLM costs",
    version="0.5.0",
    lifespan=lifespan,
)


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
        _client = httpx.AsyncClient(timeout=timeout)
    return _client


# ---------------------------------------------------------------------------
# Core proxy logic
# ---------------------------------------------------------------------------


async def _proxy_request(
    path: str,
    method: str,
    headers: dict,
    body: bytes | None = None,
    stream: bool = False,
) -> Response:
    """Forward a request to the upstream API, with optimization in between."""
    start = time.time()

    # Determine model from body
    model = "gpt-4o"
    messages = []
    if body:
        try:
            data = json.loads(body)
            model = data.get("model", model)
            messages = data.get("messages", [])
        except json.JSONDecodeError:
            pass

    if not messages:
        return await _forward_raw(path, method, headers, body, stream)

    # --- Step 0: Budget check ---
    original_tokens = count_tokens(json.dumps(messages), model)
    estimated_cost = estimate_cost_usd(original_tokens, model)
    budget = _get_budget_guard().check(estimated_cost)

    if budget.action == BudgetAction.BLOCK:
        logger.warning("Budget BLOCKED: %s (spent $%.2f / $%.2f)",
                       budget.reason, budget.spent_today, budget.daily_limit)
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": f"Tokenxygen budget limit reached: {budget.reason}. "
                               f"Spent ${budget.spent_today:.2f} of ${budget.daily_limit:.2f} today.",
                    "type": "budget_exceeded",
                    "code": "budget_exceeded",
                }
            },
        )

    # --- Step 1: Check cache ---
    if settings.cache.enabled:
        cache = _get_cache()
        cached = cache.get(messages, model)
        if cached is not None:
            logger.info("Cache HIT for model=%s", model)
            cached["_tokenxygen"] = {
                "cache_hit": True,
                "original_tokens": original_tokens,
                "optimized_tokens": 0,
                "strategies": ["cache"],
            }
            return JSONResponse(content=cached)

    # --- Step 2: Compress ---
    strategies = []

    if settings.compress.enabled:
        # Use aggressive compression if budget is tight
        compress = compressor
        if budget.action == BudgetAction.AGGRESSIVE_COMPRESS:
            compress = PromptCompressor(aggressiveness=0.8)
            strategies.append("aggressive_compress")

        messages, results = compress.compress(messages, model)
        if results:
            strategies.extend([r.strategy for r in results])
            total_saved = sum(r.saved_tokens for r in results)
            if total_saved > 0:
                logger.info(
                    "Compressed %d → %d tokens (saved %d, strategies: %s)",
                    original_tokens,
                    count_tokens(json.dumps(messages), model),
                    total_saved,
                    strategies,
                )

    # --- Step 3: Smart routing ---
    if settings.router.enabled:
        token_count = count_tokens(json.dumps(messages), model)
        decision = router.route(messages, model, token_count)

        if decision.routed_model != model:
            strategies.append(f"route:{model}→{decision.routed_model}")
            logger.info("Routed %s→%s (tier=%s, reason=%s)",
                        model, decision.routed_model, decision.tier.name, decision.reason)

        # If budget says downgrade, force cheapest model
        if budget.action == BudgetAction.DOWNGRADE and decision.routed_model == model:
            if model in ("gpt-4o", "gpt-4-turbo"):
                strategies.append(f"budget_downgrade:{model}→{settings.router.cheap_model}")
                decision.routed_model = settings.router.cheap_model

        model = decision.routed_model

    # --- Step 4: Forward to upstream ---
    optimized_tokens = count_tokens(json.dumps(messages), model)

    # Rebuild body with compressed messages
    if body:
        data = json.loads(body)
        data["messages"] = messages
        data["model"] = model
        body = json.dumps(data).encode()

    response = await _forward_raw(path, method, headers, body, stream)

    # --- Step 5: Cache the response (for non-streaming) ---
    if settings.cache.enabled and not stream and response.status_code == 200:
        try:
            resp_data = json.loads(response.body)
            _get_cache().put(messages, resp_data, model, optimized_tokens)
        except Exception as e:
            logger.warning("Failed to cache response: %s", e)

    # --- Step 6: Record analytics ---
    cost_before = estimate_cost_usd(original_tokens, model)
    cost_after = estimate_cost_usd(optimized_tokens, model)

    if settings.analytics.enabled:
        _get_analytics().record(
            RequestRecord(
                timestamp=time.time(),
                model=model,
                original_tokens=original_tokens,
                optimized_tokens=optimized_tokens,
                cache_hit=False,
                strategies_used=strategies,
                cost_before_usd=cost_before,
                cost_after_usd=cost_after,
            )
        )

    # Record to budget ledger
    _get_budget_guard().record_cost(cost_after)

    # Add optimization headers
    response.headers["X-Tokenxygen-Original-Tokens"] = str(original_tokens)
    response.headers["X-Tokenxygen-Optimized-Tokens"] = str(optimized_tokens)
    response.headers["X-Tokenxygen-Saved"] = str(original_tokens - optimized_tokens)
    response.headers["X-Tokenxygen-Strategies"] = ",".join(strategies) if strategies else "none"

    # Record metrics
    duration_ms = (time.time() - start) * 1000
    metrics.record_request(
        original_tokens=original_tokens,
        optimized_tokens=optimized_tokens,
        duration_ms=duration_ms,
        cache_hit=False,
        strategies=strategies,
        model=model,
        cost_saved_usd=cost_before - cost_after,
    )

    return response


def _validate_upstream_url(url: str) -> bool:
    """Validate upstream URL to prevent SSRF."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    
    # Block local/private IPs
    blocked_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]")
    if parsed.hostname in blocked_hosts:
        return False
    
    # Block private IP ranges
    if parsed.hostname:
        import ipaddress
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            pass  # hostname is not an IP
    
    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return False
    
    return True


async def _forward_raw(
    path: str,
    method: str,
    headers: dict,
    body: bytes | None,
    stream: bool,
) -> Response:
    """Forward raw request to upstream."""
    client = await get_client()
    upstream = f"{settings.proxy.upstream_base_url}/{path}"
    
    # Validate upstream URL to prevent SSRF
    if not _validate_upstream_url(upstream):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid upstream URL"},
        )

    # Filter headers — only forward relevant ones
    forward_headers = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in ("authorization", "content-type", "accept", "openai-organization"):
            forward_headers[key] = value

    # Ensure we have an API key
    if "authorization" not in {k.lower(): v for k, v in forward_headers.items()}:
        if settings.proxy.api_key:
            forward_headers["Authorization"] = f"Bearer {settings.proxy.api_key}"

    req = client.build_request(
        method=method,
        url=upstream,
        headers=forward_headers,
        content=body,
    )

    if stream:
        upstream_resp = await client.send(req, stream=True)

        async def stream_gen() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk
            finally:
                await upstream_resp.aclose()

        return StreamingResponse(
            stream_gen(),
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )
    else:
        upstream_resp = await client.send(req)
        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )


# ---------------------------------------------------------------------------
# Routes — specific routes BEFORE catch-all
# ---------------------------------------------------------------------------


def _check_rate_limit(client_ip: str) -> bool:
    """Check if client is within rate limit. Returns True if allowed."""
    now = time.time()
    
    with _rate_limit_lock:
        if client_ip not in _rate_limit_store:
            _rate_limit_store[client_ip] = []

        # Remove old entries
        window = settings.proxy.rate_limit_window
        _rate_limit_store[client_ip] = [
            t for t in _rate_limit_store[client_ip]
            if now - t < window
        ]

        if len(_rate_limit_store[client_ip]) >= settings.proxy.rate_limit_requests:
            return False

        _rate_limit_store[client_ip].append(now)
        return True


def _check_admin_auth(request: Request) -> bool:
    """Check for admin API key in request header.

    Returns True only if a valid admin key is provided.
    Denies access when no admin key is configured (fail-secure default).
    """
    admin_key = settings.proxy.admin_key
    if not admin_key:
        return False  # No key configured = deny access (fail-secure)
    provided = request.headers.get("X-Admin-Key", "")
    return provided == admin_key


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.5.0"}


@app.get("/tokenxygen/stats")
async def stats():
    """Return Tokenxygen analytics."""
    return {
        "today": _get_analytics().today_summary(),
        "all_time": _get_analytics().all_time_summary(),
        "cache": _get_cache().stats(),
        "budget": {
            "daily_limit": settings.budget.daily_limit_usd,
            "breakdown": _get_budget_guard().get_daily_breakdown(),
        },
    }


@app.get("/tokenxygen/budget")
async def budget_status():
    """Return current budget status."""
    budget = _get_budget_guard().check()
    return {
        "daily_limit": budget.daily_limit,
        "spent_today": budget.spent_today,
        "remaining": budget.remaining,
        "utilization": round(budget.utilization, 4),
        "action": budget.action.value,
        "reason": budget.reason,
        "breakdown": _get_budget_guard().get_daily_breakdown(),
    }


@app.post("/tokenxygen/budget/limit")
async def set_budget_limit(request: Request):
    """Set the daily budget limit."""
    if not _check_admin_auth(request):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    
    body = await request.json()
    limit = body.get("limit_usd")
    if limit is None or not isinstance(limit, (int, float)) or limit < 0:
        return JSONResponse(
            status_code=400,
            content={"error": "limit_usd must be a positive number"},
        )
    _get_budget_guard().set_daily_limit(float(limit))
    return {"daily_limit_usd": limit}


@app.post("/tokenxygen/cache/clear")
async def clear_cache(request: Request):
    """Clear the semantic cache."""
    if not _check_admin_auth(request):
        return JSONResponse(status_code=403, content={"error": "Forbidden"})
    
    count = _get_cache().clear()
    return {"cleared": count}


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from fastapi.responses import PlainTextResponse

    # Update gauge metrics
    cache = _get_cache()
    cache_stats = cache.stats()
    metrics.gauge("tokenxygen_cache_entries", cache_stats["entries"])
    metrics.gauge("tokenxygen_cache_total_hits", cache_stats["total_hits"])

    return PlainTextResponse(
        content=metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/metrics/json")
async def json_metrics():
    """JSON metrics endpoint (for dashboard)."""
    return metrics.to_dict()


# Catch-all route MUST be last
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_all(request: Request, path: str):
    """Catch-all proxy route — forwards any request to upstream."""
    # Rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": f"Rate limit exceeded. Max {settings.proxy.rate_limit_requests} requests per {int(settings.proxy.rate_limit_window)} seconds."},
        )
    
    # Request size limit (10MB)
    body = await request.body()
    if len(body) > _MAX_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={"error": "Request too large. Max 10MB."},
        )
    
    headers = dict(request.headers)
    is_stream = False

    if body:
        try:
            data = json.loads(body)
            is_stream = data.get("stream", False)
        except json.JSONDecodeError:
            pass

    return await _proxy_request(path, request.method, headers, body, stream=is_stream)
