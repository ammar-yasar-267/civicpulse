"""Aggregate statistics with a read-through cache (§2.4 job 1).

Read-through means the caller asks for stats and never asks whether they are cached: this
service checks Redis, computes on a miss, writes back with a 30s TTL, and reports which
path it took so the route can set X-Cache and the UI can show its own cache behaviour.
"""

from datetime import UTC, datetime

from app.config import Settings
from app.providers.cache import CacheProvider
from app.repositories.complaints import ComplaintRepository
from app.schemas import Stats


class StatsService:
    def __init__(
        self,
        repository: ComplaintRepository,
        cache: CacheProvider,
        settings: Settings,
    ) -> None:
        self._repo = repository
        self._cache = cache
        self._settings = settings

    def get_stats(self) -> tuple[Stats, bool]:
        """Return the aggregates and whether they came from cache (True = HIT)."""
        cached = self._cache.get_stats()
        if cached is not None:
            try:
                return Stats.model_validate(cached), True
            except Exception:
                # Shape drifted across a deploy; recompute rather than serve nonsense.
                self._cache.invalidate_stats()

        stats = self._compute()
        self._cache.set_stats(stats.model_dump(mode="json"), self._settings.stats_cache_ttl_seconds)
        return stats, False

    def _compute(self) -> Stats:
        """Four aggregate queries rather than one clever one: each is index-friendly and
        individually explainable at viva, which is worth more than saving a round trip on a
        response that is cached for 30 seconds anyway."""
        return Stats(
            total=self._repo.total(),
            by_category=self._repo.counts_by("category"),
            by_priority=self._repo.counts_by("priority"),
            by_status=self._repo.counts_by("status"),
            generated_at=datetime.now(UTC),
        )
