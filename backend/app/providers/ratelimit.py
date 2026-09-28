"""Distributed rate limiter — Redis's job 2 (§2.4).

It must be in Redis rather than an in-process dict, and the reason is the whole point of
the requirement: the moment the HPA scales the backend to four pods, four in-process
limiters each permit the full allowance and the effective limit is 4x what you configured.
State shared across replicas is the only kind that survives autoscaling.

Fixed window, implemented as INCR + EXPIRE in a single pipeline round-trip. A sliding
window would be smoother at the boundary; a fixed window is two commands and is honest
about what it is. The trade-off is documented rather than hidden: a caller can send up to
2x the limit across a window boundary, which is acceptable for protecting a free LLM tier
from a for-loop and is noted in docs/ENGINEERING-NOTES.md.
"""

import logging
from dataclasses import dataclass

import redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_PREFIX = "civicpulse:ratelimit:v1:"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, client: redis.Redis, limit: int, window_seconds: int) -> None:
        self._client = client
        self._limit = limit
        self._window = window_seconds

    def _key(self, identifier: str) -> str:
        return f"{_PREFIX}{identifier}"

    def check(self, identifier: str) -> RateLimitDecision:
        """Count this request against the caller's window and say whether to serve it.

        Fails OPEN if Redis is unreachable: a broken limiter must not take down complaint
        intake. The exposure is bounded — the LLM layer has its own timeout, retry cap and
        fallback — and losing citizen reports is the worse failure.
        """
        key = self._key(identifier)
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            count = int(count)
            ttl = int(ttl)

            # First request in a window, or a key that somehow lost its expiry.
            if ttl < 0:
                self._client.expire(key, self._window)
                ttl = self._window
        except RedisError as exc:
            logger.warning(
                "rate limiter unavailable, failing open",
                extra={"error": str(exc), "identifier_hash": hash(identifier)},
            )
            return RateLimitDecision(True, self._limit, self._limit, 0)

        if count > self._limit:
            return RateLimitDecision(False, self._limit, 0, max(ttl, 1))
        return RateLimitDecision(True, self._limit, max(self._limit - count, 0), 0)


def client_identifier(client_host: str | None, forwarded_for: str | None) -> str:
    """Key the limiter by client IP (§2.4).

    Behind the nginx frontend and a Kubernetes Ingress the socket peer is a proxy, so the
    left-most X-Forwarded-For entry is the real caller. This is spoofable by a direct
    caller, which is fine for quota protection and would not be fine for authorisation —
    a distinction worth stating out loud.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"
