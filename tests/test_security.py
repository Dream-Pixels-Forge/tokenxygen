"""Tests for security features — rate limiting, SSRF prevention."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from tokenxygen.core.proxy import app
    return TestClient(app)


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_allows_requests_under_limit(self, client):
        """Requests under limit should be allowed."""
        response = client.get("/tokenxygen/stats")
        assert response.status_code == 200

    def test_blocks_requests_over_limit(self, client):
        """Requests over limit should be blocked with 429."""
        from tokenxygen.core.proxy import RATE_LIMIT_REQUESTS
        
        # Fill up the rate limit store
        ip = "testclient"
        old_store = {ip: [time.time()] * RATE_LIMIT_REQUESTS}
        with patch("tokenxygen.core.proxy._rate_limit_store", old_store):
            # Use catch-all route which has rate limiting
            response = client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}]},
            )
            assert response.status_code == 429

    def test_rate_limit_window_expires(self, client):
        """Old entries should be cleaned up after window expires."""
        from tokenxygen.core.proxy import RATE_LIMIT_WINDOW
        
        # Add old entries
        ip = "testclient"
        old_time = time.time() - RATE_LIMIT_WINDOW - 1
        old_store = {ip: [old_time] * 5}
        with patch("tokenxygen.core.proxy._rate_limit_store", old_store):
            response = client.get("/tokenxygen/stats")
            assert response.status_code == 200


class TestSSRFPrevention:
    """Test SSRF prevention."""

    def test_blocks_localhost(self):
        """Should block localhost URLs."""
        from tokenxygen.core.proxy import _validate_upstream_url
        
        assert _validate_upstream_url("http://localhost/v1") is False
        assert _validate_upstream_url("http://127.0.0.1/v1") is False
        assert _validate_upstream_url("http://[::1]/v1") is False

    def test_blocks_private_ips(self):
        """Should block private IP ranges."""
        from tokenxygen.core.proxy import _validate_upstream_url
        
        assert _validate_upstream_url("http://192.168.1.1/v1") is False
        assert _validate_upstream_url("http://10.0.0.1/v1") is False
        assert _validate_upstream_url("http://172.16.0.1/v1") is False

    def test_allows_public_urls(self):
        """Should allow public URLs."""
        from tokenxygen.core.proxy import _validate_upstream_url
        
        assert _validate_upstream_url("https://api.openai.com/v1") is True
        assert _validate_upstream_url("https://api.anthropic.com/v1") is True

    def test_blocks_non_http_protocols(self):
        """Should block non-HTTP protocols."""
        from tokenxygen.core.proxy import _validate_upstream_url
        
        assert _validate_upstream_url("file:///etc/passwd") is False
        assert _validate_upstream_url("ftp://example.com") is False


class TestRequestSizeLimit:
    """Test request size limiting."""

    def test_rejects_large_requests(self, client):
        """Requests over 10MB should be rejected."""
        # Create a large body (but not actually 10MB for test speed)
        large_body = "x" * (10 * 1024 * 1024 + 1)
        response = client.post(
            "/v1/chat/completions",
            content=large_body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
