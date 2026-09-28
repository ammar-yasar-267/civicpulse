"""Aggregate statistics with the cache state exposed in a header (§2.2, §2.4)."""

from fastapi import APIRouter, Response

from app.dependencies import StatsServiceDep
from app.schemas import Stats

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=Stats)
def get_stats(response: Response, service: StatsServiceDep) -> Stats:
    """Redis-cached aggregates, 30s TTL, X-Cache: HIT|MISS.

    The header is the contract the frontend reads to show its own cache behaviour. It is set
    from what the service actually did, not from whether a cache is configured — otherwise
    it would claim HIT while Redis was down.
    """
    stats, cache_hit = service.get_stats()
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"
    return stats
