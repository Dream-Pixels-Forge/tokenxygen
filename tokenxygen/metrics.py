"""Prometheus metrics for monitoring TokenSaver in production.

Exposes metrics at /metrics endpoint for scraping by Prometheus.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional


@dataclass
class Counter:
    """Simple counter metric."""

    name: str
    help: str = ""
    value: float = 0.0
    labels: dict = field(default_factory=dict)

    def inc(self, value: float = 1.0) -> None:
        self.value += value

    def to_prometheus(self) -> str:
        label_str = ""
        if self.labels:
            pairs = [f'{k}="{v}"' for k, v in sorted(self.labels.items())]
            label_str = "{" + ",".join(pairs) + "}"
        return f"# HELP {self.name} {self.help}\n{self.name}{label_str} {self.value}"


@dataclass
class Histogram:
    """Simple histogram metric."""

    name: str
    help: str = ""
    buckets: list[float] = field(default_factory=lambda: [10, 50, 100, 250, 500, 1000, 2500, 5000])
    counts: dict[float, int] = field(default_factory=dict)
    total: float = 0.0
    count: int = 0

    def observe(self, value: float) -> None:
        self.total += value
        self.count += 1
        for bucket in self.buckets:
            if value <= bucket:
                self.counts[bucket] = self.counts.get(bucket, 0) + 1

    def to_prometheus(self) -> str:
        lines = [f"# HELP {self.name} {self.help}"]
        for bucket in self.buckets:
            count = self.counts.get(bucket, 0)
            lines.append(f'{self.name}_bucket{{le="{bucket}"}} {count}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self.count}')
        lines.append(f"{self.name}_sum {self.total}")
        lines.append(f"{self.name}_count {self.count}")
        return "\n".join(lines)


class MetricsCollector:
    """Collect and expose Prometheus metrics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, float] = {}

        # Initialize standard metrics
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize standard TokenSaver metrics."""
        # Counters
        self.counter("tokenxygen_requests_total", "Total requests processed")
        self.counter("tokenxygen_cache_hits_total", "Total cache hits")
        self.counter("tokenxygen_cache_misses_total", "Total cache misses")
        self.counter("tokenxygen_tokens_saved_total", "Total tokens saved")
        self.counter("tokenxygen_cost_saved_usd_total", "Total cost saved in USD")
        self.counter("tokenxygen_budget_blocks_total", "Total requests blocked by budget")
        self.counter("tokenxygen_routing_downgrades_total", "Total model downgrades")
        self.counter("tokenxygen_failover_attempts_total", "Total failover attempts")

        # Histograms
        self.histogram("tokenxygen_request_duration_ms", "Request duration in milliseconds")
        self.histogram("tokenxygen_compression_ratio", "Compression ratio (0-1)")
        self.histogram("tokenxygen_tokens_per_request", "Tokens per request")

    def counter(self, name: str, help: str = "") -> Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name, help=help)
            return self._counters[name]

    def histogram(self, name: str, help: str = "") -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name=name, help=help)
            return self._histograms[name]

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def record_request(
        self,
        original_tokens: int,
        optimized_tokens: int,
        duration_ms: float,
        cache_hit: bool,
        strategies: list[str],
        model: str,
        cost_saved_usd: float = 0.0,
    ) -> None:
        """Record a complete request with all metrics."""
        with self._lock:
            # Request count
            self._counters["tokenxygen_requests_total"].inc()

            # Cache metrics
            if cache_hit:
                self._counters["tokenxygen_cache_hits_total"].inc()
            else:
                self._counters["tokenxygen_cache_misses_total"].inc()

            # Token savings
            saved = original_tokens - optimized_tokens
            self._counters["tokenxygen_tokens_saved_total"].inc(saved)

            # Cost savings
            if cost_saved_usd > 0:
                self._counters["tokenxygen_cost_saved_usd_total"].inc(cost_saved_usd)

            # Routing downgrades
            if any("route:" in s or "budget_downgrade:" in s for s in strategies):
                self._counters["tokenxygen_routing_downgrades_total"].inc()

            # Histograms
            self._histograms["tokenxygen_request_duration_ms"].observe(duration_ms)
            self._histograms["tokenxygen_tokens_per_request"].observe(float(original_tokens))

            if original_tokens > 0:
                ratio = optimized_tokens / original_tokens
                self._histograms["tokenxygen_compression_ratio"].observe(ratio)

    def to_prometheus(self) -> str:
        """Export all metrics in Prometheus format."""
        lines = []

        with self._lock:
            for counter in self._counters.values():
                lines.append(counter.to_prometheus())
                lines.append("")

            for histogram in self._histograms.values():
                lines.append(histogram.to_prometheus())
                lines.append("")

            for name, value in self._gauges.items():
                lines.append(f"{name} {value}")
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export metrics as a dictionary (for JSON API)."""
        with self._lock:
            return {
                "counters": {k: v.value for k, v in self._counters.items()},
                "histograms": {
                    k: {
                        "count": v.count,
                        "total": v.total,
                        "avg": v.total / v.count if v.count > 0 else 0,
                    }
                    for k, v in self._histograms.items()
                },
                "gauges": dict(self._gauges),
            }


# Global singleton
metrics = MetricsCollector()
