"""TokenSaver proxy server — OpenAI-compatible API that optimizes tokens in-flight."""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from tokensaver.analytics import RequestRecord, _get_analytics
from tokensaver.cache import _get_cache
from tokensaver.compress import compressor
from tokensaver.config import settings
from tokensaver.core import count_tokens, estimate_cost_usd

logger = logging.getLogger("tokensaver")

app = FastAPI(
    title="TokenSaver",
    description="Universal token optimizer for coding agents",
    version="0.1.0",
)

# Shared HTTP client for upstream requests
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=120.0)
    return _client


@app.on_event("shutdown")
async def shutdown():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()


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

    # --- Step 1: Check cache ---
    if settings.cache.enabled:
        cache = _get_cache()
        cached = cache.get(messages, model)
        if cached is not None:
            logger.info("Cache HIT for model=%s", model)
            cached["_tokensaver"] = {
                "cache_hit": True,
                "original_tokens": count_tokens(str(messages), model),
                "optimized_tokens": 0,
                "strategies": ["cache"],
            }
            return JSONResponse(content=cached)

    # --- Step 2: Compress ---
    original_tokens = count_tokens(json.dumps(messages), model)
    strategies = []

    if settings.compress.enabled:
        messages, results = compressor.compress(messages, model)
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

    # --- Step 3: Route to cheapest model (simple heuristic) ---
    if settings.router.enabled and not strategies:
        est_tokens = count_tokens(json.dumps(messages), model)
        if est_tokens < settings.router.simple_threshold:
            # Use cheap model for simple prompts
            if model in ("gpt-4o", "gpt-4-turbo"):
                strategies.append(f"route:{model}→{settings.router.cheap_model}")
                model = settings.router.cheap_model
                # Update model in body
                if body:
                    data = json.loads(body)
                    data["model"] = model
                    body = json.dumps(data).encode()

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
        except Exception:
            pass

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

    # Add optimization headers
    response.headers["X-TokenSaver-Original-Tokens"] = str(original_tokens)
    response.headers["X-TokenSaver-Optimized-Tokens"] = str(optimized_tokens)
    response.headers["X-TokenSaver-Saved"] = str(original_tokens - optimized_tokens)
    response.headers["X-TokenSaver-Strategies"] = ",".join(strategies) if strategies else "none"

    return response


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
# Routes
# ---------------------------------------------------------------------------

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_all(request: Request, path: str):
    """Catch-all proxy route — forwards any request to upstream."""
    body = await request.body()
    headers = dict(request.headers)
    is_stream = False

    if body:
        try:
            data = json.loads(body)
            is_stream = data.get("stream", False)
        except json.JSONDecodeError:
            pass

    return await _proxy_request(path, request.method, headers, body, stream=is_stream)


@app.get("/tokensaver/stats")
async def stats():
    """Return TokenSaver analytics."""
    return {
        "today": _get_analytics().today_summary(),
        "all_time": _get_analytics().all_time_summary(),
        "cache": _get_cache().stats(),
    }


@app.post("/tokensaver/cache/clear")
async def clear_cache():
    """Clear the semantic cache."""
    count = _get_cache().clear()
    return {"cleared": count}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
