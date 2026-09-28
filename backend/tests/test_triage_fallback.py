"""The test the assignment says to write if you write no other (§2.5):

    given a provider that always raises, POST /api/complaints still returns 201
    and triaged_by == "rules:fallback".

Plus the rest of the resilience contract around it: what is retried, what is not, and what
gets recorded. None of it sleeps and none of it touches a network — the failing provider is
injected, which is the design answer to testing a probabilistic component (§2.5
"Determinism").
"""

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import TriagedBy
from app.providers.cache import CacheProvider
from app.providers.triage.base import (
    TriageBadRequest,
    TriageMalformedOutput,
    TriageRateLimited,
    TriageTimeout,
    TriageUpstreamError,
)
from app.services.triage_service import TriageService
from tests.conftest import sample_result, unique_payload
from tests.fakes import AlwaysRaisingProvider, FlakyProvider, StaticProvider


def test_post_complaint_returns_201_with_rules_fallback_when_provider_always_raises(
    app, unlimited_client: TestClient, cache: CacheProvider, test_settings
) -> None:
    """A third party being down must never become a user's 500."""
    app.state.triage_service = TriageService(
        provider=AlwaysRaisingProvider(TriageUpstreamError("groq is on fire")),
        cache=cache,
        settings=test_settings,
    )

    response = unlimited_client.post("/api/complaints", json=unique_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["triaged_by"] == TriagedBy.RULES_FALLBACK.value
    # The complaint is still usefully classified, not dumped into "other".
    assert body["category"] == "sanitation"
    assert body["ai_summary"]


def test_fallback_is_recorded_on_the_observability_surface(
    app, unlimited_client: TestClient, cache: CacheProvider, test_settings
) -> None:
    app.state.triage_service = TriageService(
        provider=AlwaysRaisingProvider(TriageTimeout("too slow")),
        cache=cache,
        settings=test_settings,
    )

    unlimited_client.post("/api/complaints", json=unique_payload())
    meta = unlimited_client.get("/api/meta/providers").json()

    assert meta["recent_outcomes"], "a triage attempt should appear in recent outcomes"
    latest = meta["recent_outcomes"][0]
    assert latest["fallback"] is True
    assert latest["provider"] == TriagedBy.RULES_FALLBACK.value
    assert latest["complaint_id"] is not None


@pytest.mark.parametrize(
    "error",
    [TriageTimeout("t"), TriageRateLimited("429"), TriageUpstreamError("500")],
    ids=["timeout", "rate_limited", "upstream_5xx"],
)
def test_retryable_errors_are_retried_exactly_once(
    cache: CacheProvider, test_settings, error: Exception
) -> None:
    """Once, not forever: a retry storm against a rate-limited provider makes things worse."""
    provider = FlakyProvider(failures=1, exc=error, result=sample_result())
    service = TriageService(provider, cache, test_settings)

    decision = service.triage("burst main flooding the street", "Street 12")

    assert provider.calls == 2, "expected one retry after a retryable failure"
    assert decision.fallback is False
    assert decision.triaged_by is TriagedBy.LLM_GROQ


@pytest.mark.parametrize(
    "error",
    [TriageBadRequest("400"), TriageMalformedOutput("prose")],
    ids=["bad_request", "malformed_output"],
)
def test_non_retryable_errors_go_straight_to_fallback(
    cache: CacheProvider, test_settings, error: Exception
) -> None:
    """A 400 was wrong and will be wrong again; malformed output means the model ignored the
    schema. Neither is improved by asking twice."""
    provider = AlwaysRaisingProvider(error)
    service = TriageService(provider, cache, test_settings)

    decision = service.triage("street light not working in our lane", "Johar Town")

    assert provider.calls == 1, "a non-retryable error must not be retried"
    assert decision.fallback is True
    assert decision.triaged_by is TriagedBy.RULES_FALLBACK


def test_retry_exhaustion_still_falls_back(cache: CacheProvider, test_settings) -> None:
    provider = FlakyProvider(failures=2, exc=TriageTimeout("t"), result=sample_result())
    service = TriageService(provider, cache, test_settings)

    decision = service.triage("gutter overflowing on main road", "Orangi Town")

    assert provider.calls == 2, "one attempt plus one retry, then give up"
    assert decision.triaged_by is TriagedBy.RULES_FALLBACK


def test_fallback_results_are_not_cached(cache: CacheProvider, test_settings) -> None:
    """Caching a degraded classification would keep serving it for 24h after the provider
    recovered — the cache must only remember real answers."""
    text, location = "transformer sparking badly near corner", "Chungi Amar Sidhu"
    service = TriageService(AlwaysRaisingProvider(), cache, test_settings)

    service.triage(text, location)

    assert cache.get_triage(text, location) is None


def test_duplicate_complaints_cost_one_inference(cache: CacheProvider, test_settings) -> None:
    """Nine neighbours, one burst main, one inference (§2.5 rule 5)."""
    provider = StaticProvider(sample_result())
    service = TriageService(provider, cache, test_settings)
    text, location = "burst main flooding street since fajr", "Street 12"

    first = service.triage(text, location)
    second = service.triage(text, location)
    # Whitespace and case differences are not a different complaint.
    third = service.triage(f"  {text.upper()}  ", location)

    assert provider.calls == 1, "cache should have served the repeats"
    assert first.cached is False
    assert second.cached is True and third.cached is True
    assert second.result.category is first.result.category
    assert cache.triage_hits == 2


def test_triage_never_raises_even_on_an_unexpected_provider_bug(
    cache: CacheProvider, test_settings
) -> None:
    """A TypeError inside a provider is a bug, not a handled failure mode — and it still must
    not reach the citizen."""
    service = TriageService(
        AlwaysRaisingProvider(TypeError("provider has a bug")), cache, test_settings
    )

    decision = service.triage("no water supply for three days", "Sector G-9")

    assert decision.triaged_by is TriagedBy.RULES_FALLBACK
    assert decision.result.category.value == "water"
