"""Tests for structured logging."""

import json
import logging

from tokenxygen.logging import (
    JSONFormatter,
    ConsoleFormatter,
    RequestLogger,
    setup_logging,
    request_id_var,
)


def test_json_formatter():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["message"] == "Test message"
    assert "timestamp" in data


def test_json_formatter_with_request_id():
    formatter = JSONFormatter()
    request_id_var.set("abc123")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["request_id"] == "abc123"

    request_id_var.set("")


def test_console_formatter():
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "INFO" in output
    assert "test:" in output
    assert "Test message" in output


def test_console_formatter_with_request_id():
    formatter = ConsoleFormatter()
    request_id_var.set("abc123def456")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "abc123" in output

    request_id_var.set("")


def test_setup_logging():
    setup_logging(level="DEBUG", json_format=False)
    logger = logging.getLogger("tokenxygen")
    assert logger.level <= logging.DEBUG


def test_request_logger_context():
    with RequestLogger(path="/v1/chat", method="POST") as req:
        assert request_id_var.get() == req.request_id
        assert len(req.request_id) == 12  # hex chars

    # Should be cleared after context
    assert request_id_var.get() == ""


def test_request_logger_log_optimization():
    with RequestLogger(path="/test", method="GET") as req:
        # Should not raise
        req.log_optimization(
            original_tokens=1000,
            optimized_tokens=500,
            strategies=["file_dedup"],
            model="gpt-4o",
        )


def test_request_logger_log_cache_hit():
    with RequestLogger() as req:
        req.log_cache_hit("gpt-4o")  # Should not raise


def test_request_logger_log_budget_action():
    with RequestLogger() as req:
        req.log_budget_action("downgrade", "at_85%_budget")


def test_request_logger_log_error():
    with RequestLogger() as req:
        req.log_error("Something failed", context={"key": "value"})
