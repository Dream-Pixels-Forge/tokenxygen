"""Tests for Prometheus metrics."""

import pytest

from tokenxygen.metrics import MetricsCollector, Counter, Histogram


def test_counter_inc():
    counter = Counter(name="test_counter")
    counter.inc()
    assert counter.value == 1
    counter.inc(5)
    assert counter.value == 6


def test_counter_to_prometheus():
    counter = Counter(name="test_total", help="Test counter")
    counter.inc(42)
    output = counter.to_prometheus()
    assert "test_total" in output
    assert "42" in output
    assert "# HELP" in output


def test_histogram_observe():
    hist = Histogram(name="test_hist")
    hist.observe(100)
    hist.observe(200)
    assert hist.count == 2
    assert hist.total == 300


def test_histogram_buckets():
    hist = Histogram(name="test_hist", buckets=[100, 200, 500])
    hist.observe(50)    # ≤100
    hist.observe(150)   # ≤200
    hist.observe(300)   # ≤500
    hist.observe(600)   # >500

    assert hist.counts.get(100, 0) == 1
    assert hist.counts.get(200, 0) == 2
    assert hist.counts.get(500, 0) == 3
    assert hist.count == 4


def test_histogram_to_prometheus():
    hist = Histogram(name="test_duration", help="Duration")
    hist.observe(100)
    output = hist.to_prometheus()
    assert "test_duration_bucket" in output
    assert "test_duration_sum" in output
    assert "test_duration_count" in output


def test_metrics_collector_init():
    collector = MetricsCollector()
    prometheus = collector.to_prometheus()
    assert "tokenxygen_requests_total" in prometheus
    assert "tokenxygen_cache_hits_total" in prometheus
    assert "tokenxygen_tokens_saved_total" in prometheus


def test_metrics_record_request():
    collector = MetricsCollector()
    collector.record_request(
        original_tokens=1000,
        optimized_tokens=600,
        duration_ms=50.0,
        cache_hit=False,
        strategies=["file_dedup"],
        model="gpt-4o",
        cost_saved_usd=0.001,
    )

    counters = collector._counters
    assert counters["tokenxygen_requests_total"].value == 1
    assert counters["tokenxygen_cache_misses_total"].value == 1
    assert counters["tokenxygen_tokens_saved_total"].value == 400
    assert counters["tokenxygen_cost_saved_usd_total"].value == 0.001


def test_metrics_cache_hit():
    collector = MetricsCollector()
    collector.record_request(
        original_tokens=100,
        optimized_tokens=0,
        duration_ms=5.0,
        cache_hit=True,
        strategies=["cache"],
        model="gpt-4o",
    )

    assert collector._counters["tokenxygen_cache_hits_total"].value == 1
    assert collector._counters["tokenxygen_cache_misses_total"].value == 0


def test_metrics_routing_downgrade():
    collector = MetricsCollector()
    collector.record_request(
        original_tokens=100,
        optimized_tokens=100,
        duration_ms=10.0,
        cache_hit=False,
        strategies=["route:gpt-4o→gpt-4o-mini"],
        model="gpt-4o-mini",
    )

    assert collector._counters["tokenxygen_routing_downgrades_total"].value == 1


def test_metrics_to_dict():
    collector = MetricsCollector()
    collector.record_request(
        original_tokens=1000,
        optimized_tokens=600,
        duration_ms=50.0,
        cache_hit=False,
        strategies=[],
        model="gpt-4o",
    )

    data = collector.to_dict()
    assert "counters" in data
    assert "histograms" in data
    assert data["counters"]["tokenxygen_requests_total"] == 1


def test_metrics_gauge():
    collector = MetricsCollector()
    collector.gauge("tokenxygen_cache_entries", 42)
    assert collector._gauges["tokenxygen_cache_entries"] == 42
