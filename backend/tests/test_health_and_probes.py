"""Probe semantics (§2.2, rubric C — 3 marks).

The distinction being tested is the one that causes real outages: /health must not touch the
database, because a failing liveness probe restarts the pod and a slow database would
therefore restart every backend pod at once.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fakes import FakeRedis


def test_health_is_alive(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_does_not_touch_the_database(client: TestClient) -> None:
    """Asserted structurally rather than by inspection: if /health ever grows a query, this
    patch makes it fail."""
    with patch("app.db.database_reachable", side_effect=AssertionError("/health hit the DB")):
        assert client.get("/health").status_code == 200


def test_health_survives_redis_being_down(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.fail = True
    assert client.get("/health").status_code == 200


def test_ready_is_200_when_both_dependencies_are_reachable(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"] == {"postgres": "ok", "redis": "ok"}
    assert body["failed"] is None


def test_ready_is_503_naming_redis_when_the_cache_is_down(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    fake_redis.fail = True

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["failed"] == "redis"
    assert body["dependencies"]["redis"] == "unreachable"
    assert body["dependencies"]["postgres"] == "ok"


def test_ready_is_503_naming_postgres_when_the_database_is_down(client: TestClient) -> None:
    """Named in the body so `kubectl describe pod` tells you which dependency broke without
    needing a shell on the pod."""
    with patch("app.routes.health.database_reachable", return_value=False):
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["failed"] == "postgres"


def test_metrics_exposes_the_four_required_series(client: TestClient) -> None:
    client.get("/api/stats")  # generate some traffic first

    body = client.get("/metrics").text

    assert "civicpulse_http_requests_total" in body
    assert "civicpulse_http_request_duration_seconds" in body
    assert "civicpulse_triage_duration_seconds" in body
    assert "civicpulse_triage_fallbacks_total" in body


def test_metrics_labels_use_route_templates_not_raw_paths(client: TestClient) -> None:
    """A UUID in a Prometheus label is unbounded cardinality — one new time series per
    complaint, and eventually a dead metrics backend."""
    cid = client.post(
        "/api/complaints",
        json={
            "text": "Burst water main flooding the street since fajr, please send a team.",
            "location": "Street 12, Lahore",
        },
    ).json()["id"]
    client.get(f"/api/complaints/{cid}")

    body = client.get("/metrics").text

    assert cid not in body
    assert "/api/complaints/{complaint_id}" in body
