"""Redis cache provider — job 1 of two (§2.4).

Behind an interface, like every outbound integration. Two consequences that matter:

* Cache failures are never user-visible. Redis being down degrades /api/stats to a slower
  uncached response, it does not 500 the dashboard. Every method here swallows RedisError
  and reports a miss.
* The triage content-hash cache and the stats cache share this one client, because Redis
  is a capability rather than a single-purpose box.
"""

import hashlib
import json
import logging
from typing import Any

import redis
from redis.exceptions import RedisError

from app.schemas import TriageResult

logger = logging.getLogger(__name__)

STATS_KEY = "civicpulse:stats:v1"
_TRIAGE_PREFIX = "civicpulse:triage:v1:"


def triage_cache_key(text: str, location: str) -> str:
    """Content hash, so nine neighbours reporting one burst main cost one inference
    rather than nine (§2.5 rule 5).

    Normalised first — case and whitespace differences are not different complaints.
    The hash also means complaint text is never itself a Redis key, which keeps PII out
    of anything an operator sees in redis-cli KEYS output.
    """
    normalised = f"{' '.join(text.lower().split())}|{' '.join(location.lower().split())}"
    return _TRIAGE_PREFIX + hashlib.sha256(normalised.encode()).hexdigest()


class CacheProvider:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        # Process-local counters for the measured hit rate reported by
        # /api/meta/providers. Per-pod by design; the aggregate lives in /metrics.
        self.triage_hits = 0
        self.triage_misses = 0

    # --- generic ---------------------------------------------------------------

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except RedisError:
            return False

    def get_json(self, key: str) -> Any | None:
        try:
            raw = self._client.get(key)
        except RedisError as exc:
            logger.warning("cache read failed", extra={"key": key, "error": str(exc)})
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # A poisoned key is not worth an outage: drop it and treat as a miss.
            logger.warning("cache value was not valid JSON, discarding", extra={"key": key})
            self.delete(key)
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            self._client.setex(key, ttl_seconds, json.dumps(value, default=str))
        except RedisError as exc:
            logger.warning("cache write failed", extra={"key": key, "error": str(exc)})

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except RedisError as exc:
            logger.warning("cache delete failed", extra={"key": key, "error": str(exc)})

    # --- job 1a: stats read-through cache --------------------------------------

    def get_stats(self) -> dict | None:
        value = self.get_json(STATS_KEY)
        return value if isinstance(value, dict) else None

    def set_stats(self, payload: dict, ttl_seconds: int) -> None:
        self.set_json(STATS_KEY, payload, ttl_seconds)

    def invalidate_stats(self) -> None:
        """Called on every write. TTL alone would leave a freshly submitted complaint
        invisible for up to 30s; invalidation alone would leave a stale entry forever if a
        write path ever forgets to call it. Both, deliberately — belt and braces, and the
        viva question in §2.4."""
        self.delete(STATS_KEY)

    # --- job 1b: triage content-hash cache ------------------------------------

    def get_triage(self, text: str, location: str) -> TriageResult | None:
        payload = self.get_json(triage_cache_key(text, location))
        if not isinstance(payload, dict):
            self.triage_misses += 1
            return None
        try:
            result = TriageResult.model_validate(payload)
        except Exception:
            # Validate on the way out as well as in: a schema change must not resurrect
            # incompatible rows written by an older build.
            self.triage_misses += 1
            return None
        self.triage_hits += 1
        return result

    def set_triage(self, text: str, location: str, result: TriageResult, ttl_seconds: int) -> None:
        self.set_json(triage_cache_key(text, location), result.model_dump(mode="json"), ttl_seconds)

    @property
    def triage_hit_rate(self) -> float:
        total = self.triage_hits + self.triage_misses
        return round(self.triage_hits / total, 4) if total else 0.0


def build_redis_client(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=2,
        socket_connect_timeout=2,
        health_check_interval=30,
    )
