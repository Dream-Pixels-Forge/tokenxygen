"""Security middleware for Tokenxygen proxy.

Features:
1. Security headers (CSP, HSTS, X-Content-Type-Options, etc.)
2. CORS configuration
3. Request validation
4. Admin authentication
"""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from tokenxygen.config import settings

import logging

logger = logging.getLogger("tokenxygen.security")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # HSTS - only enable if behind HTTPS proxy
        if settings.proxy.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={settings.proxy.hsts_max_age}; includeSubDomains"
            )

        # CSP - restrictive policy for API
        response.headers["Content-Security-Policy"] = "default-src 'none'"

        return response


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Protect admin endpoints with API key authentication."""

    # Endpoints that require admin authentication
    ADMIN_PATHS = {
        "/tokenxygen/budget/limit",
        "/tokenxygen/cache/clear",
    }

    async def dispatch(self, request: Request, call_next):
        # Only protect admin endpoints
        if request.url.path not in self.ADMIN_PATHS:
            return await call_next(request)

        # Check admin key
        admin_key = settings.proxy.admin_key
        if not admin_key:
            # No admin key configured - deny access (fail-secure)
            logger.warning("Admin endpoint accessed but no admin key configured")
            return Response(
                content='{"error": "Admin access not configured"}',
                status_code=403,
                media_type="application/json",
            )

        provided_key = request.headers.get("X-Admin-Key", "")
        if provided_key != admin_key:
            logger.warning(
                "Invalid admin key attempt from %s",
                request.client.host if request.client else "unknown",
            )
            return Response(
                content='{"error": "Invalid admin key"}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Validate incoming requests."""

    async def dispatch(self, request: Request, call_next):
        # Block obviously malicious paths
        path = request.url.path

        # Block path traversal attempts
        if ".." in path or "%2e%2e" in path.lower():
            logger.warning("Path traversal attempt blocked: %s", path)
            return Response(
                content='{"error": "Invalid path"}',
                status_code=400,
                media_type="application/json",
            )

        # Block null bytes
        if "\x00" in path:
            logger.warning("Null byte in path blocked: %s", path)
            return Response(
                content='{"error": "Invalid path"}',
                status_code=400,
                media_type="application/json",
            )

        return await call_next(request)


def setup_cors(app) -> None:
    """Configure CORS middleware based on settings."""
    if settings.proxy.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.proxy.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
            allow_headers=["*"],
            expose_headers=[
                "X-Request-ID",
                "X-Response-Time",
                "X-Tokenxygen-Original-Tokens",
                "X-Tokenxygen-Optimized-Tokens",
                "X-Tokenxygen-Saved",
                "X-Tokenxygen-Strategies",
            ],
        )


def check_admin_auth(request: Request) -> bool:
    """Check for admin API key in request header.

    Returns True only if a valid admin key is provided.
    Denies access when no admin key is configured (fail-secure default).
    """
    admin_key = settings.proxy.admin_key
    if not admin_key:
        return False  # No key configured = deny access (fail-secure)
    provided = request.headers.get("X-Admin-Key", "")
    return provided == admin_key


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    # Check for forwarded headers (when behind reverse proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and settings.proxy.trust_forwarded_headers:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()

    # Fall back to direct connection
    return request.client.host if request.client else "unknown"


def is_private_ip(ip: str) -> bool:
    """Check if an IP address is private/loopback."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False
