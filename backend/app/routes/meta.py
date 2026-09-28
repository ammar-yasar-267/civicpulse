"""The observability surface (§2.2 GET /api/meta/providers).

Answers, without a shell on the pod: which reader is active, how often the content-hash cache
is earning its keep, and what the last 20 triage attempts actually did — provider, latency and
whether they fell back. This is the endpoint that makes the AI layer's behaviour visible
instead of asserted.
"""

from fastapi import APIRouter

from app.dependencies import TriageDep
from app.schemas import ProvidersMeta

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/providers", response_model=ProvidersMeta)
def get_providers(triage: TriageDep) -> ProvidersMeta:
    hits, misses, hit_rate = triage.cache_stats()
    return ProvidersMeta(
        active_provider=triage.active_provider,
        cache_hits=hits,
        cache_misses=misses,
        cache_hit_rate=hit_rate,
        recent_outcomes=triage.recent_outcomes(),
    )
