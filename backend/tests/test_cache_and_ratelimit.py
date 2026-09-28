"""Cache and rate-limiter tests (§2.4, rubric E).

TTL expiry is tested by advancing a fake clock, never by sleeping: a suite with sleeps in it
is slow and still flaky, and the assignment calls that out specifically.
"""

from fastapi.testclient import TestClient

from app.providers.cache import CacheProvider, triage_cache_key
from app.providers.ratelimit import RateLimiter, client_identifier
from tests.conftest import unique_payload, valid_payload
from tests.fakes import FakeClock, FakeRedis

# --- stats read-through cache --------------------------------------------------


def test_stats_reports_miss_then_hit(client: TestClient) -> None:
    first = client.get("/api/stats")
    second = client.get("/api/stats")

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json()["total"] == second.json()["total"]


def test_stats_aggregates_are_correct(unlimited_client: TestClient) -> None:
    unlimited_client.post("/api/complaints", json=valid_payload())  # water / high
    unlimited_client.post(
        "/api/complaints",
        json=valid_payload(text="Street light bulb fused in our lane, please replace."),
    )  # streetlights / low

    stats = unlimited_client.get("/api/stats").json()

    assert stats["total"] == 2
    assert stats["by_category"]["water"] == 1
    assert stats["by_category"]["streetlights"] == 1
    assert stats["by_status"]["open"] == 2
    assert sum(stats["by_priority"].values()) == 2


def test_write_invalidates_the_cache_immediately(unlimited_client: TestClient) -> None:
    """TTL alone would leave a citizen staring at a dashboard that disagrees with the
    submission they just made, for up to 30 seconds (§2.4)."""
    unlimited_client.get("/api/stats")  # populate
    assert unlimited_client.get("/api/stats").headers["X-Cache"] == "HIT"

    unlimited_client.post("/api/complaints", json=unique_payload())

    after = unlimited_client.get("/api/stats")
    assert after.headers["X-Cache"] == "MISS", "a write must invalidate the cached stats"
    assert after.json()["total"] == 1


def test_status_change_also_invalidates(unlimited_client: TestClient) -> None:
    cid = unlimited_client.post("/api/complaints", json=valid_payload()).json()["id"]
    unlimited_client.get("/api/stats")
    assert unlimited_client.get("/api/stats").headers["X-Cache"] == "HIT"

    unlimited_client.patch(f"/api/complaints/{cid}/status", json={"status": "in_progress"})

    refreshed = unlimited_client.get("/api/stats")
    assert refreshed.headers["X-Cache"] == "MISS"
    assert refreshed.json()["by_status"]["in_progress"] == 1


def test_stats_cache_expires_after_its_ttl(client: TestClient, fake_clock: FakeClock) -> None:
    client.get("/api/stats")
    assert client.get("/api/stats").headers["X-Cache"] == "HIT"

    fake_clock.advance(31)  # TTL is 30s

    assert client.get("/api/stats").headers["X-Cache"] == "MISS"


def test_cache_failure_degrades_instead_of_erroring(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    """Redis down must mean 'slower stats', not 'broken dashboard'."""
    fake_redis.fail = True

    response = client.get("/api/stats")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"


# --- triage content-hash cache ------------------------------------------------


def test_triage_cache_key_normalises_whitespace_and_case() -> None:
    assert triage_cache_key("Burst  MAIN ", "Street 12") == triage_cache_key(
        "burst main", " street 12 "
    )
    assert triage_cache_key("burst main", "Street 12") != triage_cache_key(
        "burst main", "Street 13"
    )


def test_triage_cache_key_does_not_contain_complaint_text() -> None:
    """Complaint text is PII-adjacent; it must not appear in a Redis key an operator can see
    in KEYS output."""
    key = triage_cache_key("my name is Ammar and my number is 0300-1234567", "Lahore")
    assert "Ammar" not in key and "0300" not in key


def test_hit_rate_is_reported(cache: CacheProvider) -> None:
    from tests.conftest import sample_result

    assert cache.get_triage("a burst main", "Street 12") is None  # miss
    cache.set_triage("a burst main", "Street 12", sample_result(), 3600)
    assert cache.get_triage("a burst main", "Street 12") is not None  # hit

    assert cache.triage_hits == 1
    assert cache.triage_misses == 1
    assert cache.triage_hit_rate == 0.5


def test_meta_providers_exposes_hit_rate_and_outcomes(unlimited_client: TestClient) -> None:
    payload = valid_payload()
    unlimited_client.post("/api/complaints", json=payload)
    unlimited_client.post("/api/complaints", json=payload)  # identical -> cached triage

    meta = unlimited_client.get("/api/meta/providers").json()

    assert meta["active_provider"] == "rules"
    assert meta["cache_hits"] >= 1
    assert 0.0 <= meta["cache_hit_rate"] <= 1.0
    assert len(meta["recent_outcomes"]) <= 20
    assert meta["recent_outcomes"][0]["cached"] is True


# --- distributed rate limiter -------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(client: TestClient) -> None:
    """Limit in the test settings is 5/60s."""
    for _ in range(5):
        assert client.post("/api/complaints", json=unique_payload()).status_code == 201

    blocked = client.post("/api/complaints", json=unique_payload())

    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_window_resets(client: TestClient, fake_clock: FakeClock) -> None:
    for _ in range(5):
        client.post("/api/complaints", json=unique_payload())
    assert client.post("/api/complaints", json=unique_payload()).status_code == 429

    fake_clock.advance(61)

    assert client.post("/api/complaints", json=unique_payload()).status_code == 201


def test_limiter_is_shared_across_instances(fake_redis: FakeRedis) -> None:
    """The point of the requirement: two limiter objects standing in for two pods share one
    counter, so scaling out does not multiply the effective limit (§2.4)."""
    pod_a = RateLimiter(fake_redis, limit=3, window_seconds=60)  # type: ignore[arg-type]
    pod_b = RateLimiter(fake_redis, limit=3, window_seconds=60)  # type: ignore[arg-type]

    assert pod_a.check("1.2.3.4").allowed
    assert pod_b.check("1.2.3.4").allowed
    assert pod_a.check("1.2.3.4").allowed
    assert not pod_b.check("1.2.3.4").allowed, "an in-process limiter would have allowed this"


def test_limiter_keys_per_client(fake_redis: FakeRedis) -> None:
    limiter = RateLimiter(fake_redis, limit=1, window_seconds=60)  # type: ignore[arg-type]

    assert limiter.check("1.1.1.1").allowed
    assert not limiter.check("1.1.1.1").allowed
    assert limiter.check("2.2.2.2").allowed, "one noisy caller must not block everyone"


def test_limiter_fails_open_when_redis_is_down(fake_redis: FakeRedis) -> None:
    """Losing citizen complaints is worse than briefly losing quota protection — and the LLM
    layer has its own timeout, retry cap and fallback behind this."""
    limiter = RateLimiter(fake_redis, limit=1, window_seconds=60)  # type: ignore[arg-type]
    fake_redis.fail = True

    assert limiter.check("1.1.1.1").allowed


def test_client_identifier_prefers_forwarded_for() -> None:
    """Behind nginx and an Ingress the socket peer is a proxy, so the real caller is the
    left-most X-Forwarded-For entry."""
    assert client_identifier("10.0.0.1", "203.0.113.9, 10.0.0.1") == "203.0.113.9"
    assert client_identifier("10.0.0.1", None) == "10.0.0.1"
    assert client_identifier(None, None) == "unknown"
