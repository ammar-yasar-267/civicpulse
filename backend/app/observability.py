"""Prometheus metrics (§2.2 GET /metrics).

Four series, because the assignment names four and each answers a question you cannot
answer from logs at a glance: how much traffic, how slow, how slow is triage specifically,
and how often the clever reader failed.

Labels are deliberately low-cardinality — the route *template* (/api/complaints/{id}), never
the path, because a UUID in a label name is how you turn a metrics endpoint into an outage.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

REQUEST_COUNT = Counter(
    "civicpulse_http_requests_total",
    "HTTP requests by method, route template and status class.",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

REQUEST_LATENCY = Histogram(
    "civicpulse_http_request_duration_seconds",
    "HTTP request latency.",
    labelnames=("method", "route"),
    # Web-request buckets: sub-100ms matters for the dashboard, and the 10s bucket exists
    # because that is the triage timeout and submissions cluster just under it.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

TRIAGE_LATENCY = Histogram(
    "civicpulse_triage_duration_seconds",
    "Triage latency by provider and outcome.",
    labelnames=("provider", "outcome"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    registry=REGISTRY,
)

TRIAGE_FALLBACKS = Counter(
    "civicpulse_triage_fallbacks_total",
    "Times triage fell back to the rules provider, by the error class that caused it.",
    labelnames=("provider", "error_class"),
    registry=REGISTRY,
)

TRIAGE_CACHE = Counter(
    "civicpulse_triage_cache_total",
    "Triage content-hash cache lookups by result.",
    labelnames=("result",),
    registry=REGISTRY,
)

READY_GAUGE = Gauge(
    "civicpulse_dependency_up",
    "1 when a dependency answered its readiness check, 0 otherwise.",
    labelnames=("dependency",),
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
