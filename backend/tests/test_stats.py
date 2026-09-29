"""Tests for GET /api/stats and the date-range filter on GET /api/complaints.

These are the two features added in this contribution:
  1. Stats endpoint — previously untested despite being a required contract endpoint (§2.2).
  2. Date-range filtering — created_after / created_before query parameters.

Both are integration tests using real Postgres and a fake Redis, matching the style of the
existing test suite (see conftest.py for fixture details).
"""

from fastapi.testclient import TestClient

from tests.conftest import unique_payload, valid_payload


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


def test_stats_returns_correct_totals(unlimited_client: TestClient) -> None:
    """After submitting two complaints the total should be exactly two."""
    unlimited_client.post("/api/complaints", json=unique_payload())
    unlimited_client.post("/api/complaints", json=unique_payload())

    response = unlimited_client.get("/api/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert "by_category" in body
    assert "by_priority" in body
    assert "by_status" in body
    assert "generated_at" in body


def test_stats_first_call_is_cache_miss(client: TestClient) -> None:
    """The first request after a cache flush must set X-Cache: MISS."""
    response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.headers.get("X-Cache") == "MISS"


def test_stats_second_call_is_cache_hit(client: TestClient) -> None:
    """The second call within the TTL window must be served from Redis (HIT)."""
    client.get("/api/stats")  # populate the cache
    response = client.get("/api/stats")
    assert response.headers.get("X-Cache") == "HIT"


def test_stats_invalidated_after_new_complaint(unlimited_client: TestClient) -> None:
    """Submitting a complaint must bust the cache so the next stats call is a MISS
    and reflects the new total — not a stale count from before the submission."""
    unlimited_client.get("/api/stats")  # seed the cache

    unlimited_client.post("/api/complaints", json=unique_payload())

    # The cache should have been invalidated by the submit.
    response = unlimited_client.get("/api/stats")
    assert response.headers.get("X-Cache") == "MISS"
    assert response.json()["total"] == 1


def test_stats_by_status_reflects_status_change(unlimited_client: TestClient) -> None:
    """Advancing a complaint's status must flush the cache so by_status is accurate."""
    cid = unlimited_client.post("/api/complaints", json=unique_payload()).json()["id"]
    unlimited_client.get("/api/stats")  # cache the open state

    unlimited_client.patch(f"/api/complaints/{cid}/status", json={"status": "in_progress"})

    stats = unlimited_client.get("/api/stats").json()
    # Regardless of cache state, in_progress should appear in by_status.
    assert stats["by_status"].get("in_progress", 0) >= 1


def test_stats_by_category_counts_are_accurate(unlimited_client: TestClient) -> None:
    """Complaints triaged by the rules engine to 'water' must appear in by_category."""
    unlimited_client.post(
        "/api/complaints",
        json=valid_payload(),  # rules engine classifies this as water/high
    )

    stats = unlimited_client.get("/api/stats").json()
    assert stats["by_category"].get("water", 0) >= 1
    assert stats["by_priority"].get("high", 0) >= 1


# ---------------------------------------------------------------------------
# Date-range filter on GET /api/complaints
# ---------------------------------------------------------------------------


def test_created_after_excludes_earlier_complaints(unlimited_client: TestClient) -> None:
    """created_after should exclude complaints submitted before the given timestamp."""
    import datetime

    unlimited_client.post("/api/complaints", json=unique_payload())

    # Capture a timestamp after the first complaint is stored.
    cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()

    unlimited_client.post("/api/complaints", json=unique_payload())

    response = unlimited_client.get(
        "/api/complaints", params={"created_after": cutoff}
    )
    assert response.status_code == 200
    body = response.json()
    # Only the complaint submitted after the cutoff should be returned.
    assert body["total"] == 1


def test_created_before_excludes_later_complaints(unlimited_client: TestClient) -> None:
    """created_before should exclude complaints submitted after the given timestamp."""
    import datetime

    unlimited_client.post("/api/complaints", json=unique_payload())

    cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()

    unlimited_client.post("/api/complaints", json=unique_payload())

    response = unlimited_client.get(
        "/api/complaints", params={"created_before": cutoff}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


def test_date_range_combined_with_category_filter(unlimited_client: TestClient) -> None:
    """created_after can be combined with category to narrow results further."""
    import datetime

    unlimited_client.post("/api/complaints", json=unique_payload())  # sanitation/normal

    cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()

    unlimited_client.post(
        "/api/complaints",
        json=valid_payload(),  # water/high
    )

    response = unlimited_client.get(
        "/api/complaints",
        params={"created_after": cutoff, "category": "water"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "water"
