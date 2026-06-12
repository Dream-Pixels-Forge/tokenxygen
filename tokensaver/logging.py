"""Structured logging for production use.

Features:
1. JSON-formatted logs for log aggregation
2. Request/response tracking with correlation IDs
3. Performance metrics (latency, token usage)
4. Error tracking with context
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Context variable for request correlation
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_agent_var: ContextVar[str] = ContextVar("user_agent", default="")


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request context
        req_id = request_id_var.get("")
        if req_id:
            log_entry["request_id"] = req_id

        ua = user_agent_var.get("")
        if ua:
            log_entry["user_agent"] = ua

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        # Add exception info
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter."""

    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        req_id = request_id_var.get("")

        prefix = f"{color}{record.levelname:8}{self.RESET}"
        if req_id:
            prefix += f" [{req_id[:8]}]"

        return f"{prefix} {record.name}: {record.getMessage()}"


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure logging for TokenSaver.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use JSON formatting (for production)
        log_file: Optional file to write logs to
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    if json_format:
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)

    # Set tokensaver logger level
    tokensaver_logger = logging.getLogger("tokensaver")
    tokensaver_logger.setLevel(getattr(logging, level.upper(), logging.INFO))


class RequestLogger:
    """Context manager for request-scoped logging."""

    def __init__(self, path: str = "", method: str = "") -> None:
        self.request_id = uuid.uuid4().hex[:12]
        self.path = path
        self.method = method
        self.start_time = 0.0
        self.logger = logging.getLogger("tokensaver.request")

    def __enter__(self) -> RequestLogger:
        self.start_time = time.time()
        request_id_var.set(self.request_id)
        self.logger.info(
            "Request started: %s %s",
            self.method,
            self.path,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.time() - self.start_time) * 1000

        if exc_type:
            self.logger.error(
                "Request failed: %s %s (%.1fms) - %s",
                self.method,
                self.path,
                duration_ms,
                str(exc_val),
            )
        else:
            self.logger.info(
                "Request completed: %s %s (%.1fms)",
                self.method,
                self.path,
                duration_ms,
            )

        # Clear context
        request_id_var.set("")
        return None  # Don't suppress exceptions

    def log_optimization(
        self,
        original_tokens: int,
        optimized_tokens: int,
        strategies: list[str],
        model: str,
    ) -> None:
        """Log optimization details."""
        saved = original_tokens - optimized_tokens
        savings_pct = (saved / original_tokens * 100) if original_tokens > 0 else 0

        self.logger.info(
            "Optimized: %d → %d tokens (%.1f%% saved, strategies=%s, model=%s)",
            original_tokens,
            optimized_tokens,
            savings_pct,
            ",".join(strategies) if strategies else "none",
            model,
        )

    def log_cache_hit(self, model: str) -> None:
        self.logger.info("Cache HIT for model=%s", model)

    def log_cache_miss(self, model: str) -> None:
        self.logger.debug("Cache MISS for model=%s", model)

    def log_budget_action(self, action: str, reason: str) -> None:
        self.logger.warning("Budget action: %s (%s)", action, reason)

    def log_routing(self, original: str, routed: str, tier: str) -> None:
        self.logger.info("Routed: %s → %s (tier=%s)", original, routed, tier)

    def log_error(self, error: str, context: dict | None = None) -> None:
        extra = {"extra_data": context} if context else {}
        self.logger.error("Error: %s", error, extra=extra)


# Pre-configured loggers
proxy_logger = logging.getLogger("tokensaver.proxy")
cache_logger = logging.getLogger("tokensaver.cache")
compress_logger = logging.getLogger("tokensaver.compress")
router_logger = logging.getLogger("tokensaver.router")
budget_logger = logging.getLogger("tokensaver.budget")
analytics_logger = logging.getLogger("tokensaver.analytics")
