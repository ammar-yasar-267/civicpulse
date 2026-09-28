"""Triage orchestration — the engineering around the model (§2.5).

Calling an LLM is four lines; this file is the assignment. It owns, in order:

  1. content-hash cache lookup      — duplicates cost one inference, not nine
  2. the provider call              — behind the TriageProvider seam, timeout enforced there
  3. one retry, jittered            — timeout / 429 / 5xx only, never a 400
  4. fallback to RuleBasedTriage    — records triaged_by = "rules:fallback"
  5. latency measurement            — you cannot reason about cost without measuring it
  6. an outcome ring buffer         — the observability surface behind /api/meta/providers

The invariant every other layer relies on: triage() does not raise. A third party being
rate-limited can never become a user's 500.
"""

import logging
import random
import time
import uuid
from collections import deque
from datetime import UTC, datetime

from app.config import Settings
from app.domain.enums import TriagedBy
from app.providers.cache import CacheProvider
from app.providers.triage.base import (
    TriageBadRequest,
    TriageError,
    TriageMalformedOutput,
    TriageProvider,
    TriageRateLimited,
    TriageTimeout,
    TriageUpstreamError,
)
from app.providers.triage.factory import build_fallback
from app.schemas import TriageOutcome, TriageResult

logger = logging.getLogger(__name__)

# Only these are worth a second attempt: the request was fine, the far end was not.
RETRYABLE = (TriageTimeout, TriageRateLimited, TriageUpstreamError)

_PROVIDER_TO_TRIAGED_BY = {
    "llm:groq": TriagedBy.LLM_GROQ,
    "llm:ollama": TriagedBy.LLM_OLLAMA,
    "rules": TriagedBy.RULES,
    "simulated": TriagedBy.SIMULATED,
}

RECENT_OUTCOMES_LIMIT = 20


class TriageDecision:
    """What the service resolved, plus how it got there. Carried into the repository so
    triaged_by and triage_latency_ms are persisted per §2.3."""

    def __init__(
        self,
        result: TriageResult,
        triaged_by: TriagedBy,
        latency_ms: int,
        fallback: bool,
        cached: bool,
    ) -> None:
        self.result = result
        self.triaged_by = triaged_by
        self.latency_ms = latency_ms
        self.fallback = fallback
        self.cached = cached


class TriageService:
    def __init__(
        self,
        provider: TriageProvider,
        cache: CacheProvider,
        settings: Settings,
        fallback: TriageProvider | None = None,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._settings = settings
        self._fallback = fallback or build_fallback()
        self._recent: deque[TriageOutcome] = deque(maxlen=RECENT_OUTCOMES_LIMIT)

    @property
    def active_provider(self) -> str:
        return self._provider.name

    def recent_outcomes(self) -> list[TriageOutcome]:
        """Newest first — an operator reading a dashboard wants the last thing that
        happened at the top."""
        return list(reversed(self._recent))

    def triage(self, text: str, location: str, request_id: str | None = None) -> TriageDecision:
        """Classify a complaint. Never raises."""
        cached = self._cache.get_triage(text, location)
        if cached is not None:
            decision = TriageDecision(
                result=cached,
                triaged_by=self._triaged_by_for(self._provider.name),
                latency_ms=0,  # a cache hit cost no inference; recording real time would
                # pollute the latency series we use to reason about cost
                fallback=False,
                cached=True,
            )
            self._record(decision, request_id)
            return decision

        started = time.perf_counter()
        try:
            result = self._call_with_retry(text, location, request_id)
        except TriageError as exc:
            return self._fall_back(text, location, started, exc, request_id)
        except Exception as exc:  # a provider bug must not become a 500 either
            return self._fall_back(text, location, started, exc, request_id)

        latency_ms = self._elapsed_ms(started)
        self._cache.set_triage(text, location, result, self._settings.triage_cache_ttl_seconds)

        decision = TriageDecision(
            result=result,
            triaged_by=self._triaged_by_for(self._provider.name),
            latency_ms=latency_ms,
            fallback=False,
            cached=False,
        )
        self._record(decision, request_id)
        return decision

    # --- internals -------------------------------------------------------------

    def _call_with_retry(self, text: str, location: str, request_id: str | None) -> TriageResult:
        """One attempt, then at most one more (§2.5 rule 3)."""
        try:
            return self._provider.triage(text, location)
        except RETRYABLE as exc:
            delay = self._jittered_delay()
            logger.warning(
                "triage attempt failed, retrying once",
                extra={
                    "provider": self._provider.name,
                    "error_class": type(exc).__name__,
                    "retry_delay_seconds": round(delay, 3),
                    "request_id": request_id,
                },
            )
            time.sleep(delay)
            return self._provider.triage(text, location)
        except (TriageBadRequest, TriageMalformedOutput):
            # Not retryable: a 400 was wrong and will be wrong again; malformed output
            # means the model ignored the schema, and asking twice is not a fix.
            raise

    def _jittered_delay(self) -> float:
        """Full jitter over a 250-750ms base. Jitter matters because every pod retrying on
        the same schedule turns one provider hiccup into a synchronised thundering herd."""
        return random.uniform(0.25, 0.75)

    def _fall_back(
        self,
        text: str,
        location: str,
        started: float,
        exc: Exception,
        request_id: str | None,
    ) -> TriageDecision:
        """Rules floor. One WARNING per fallback carrying the provider and error class,
        as required by §2.2 structured logging."""
        result = self._fallback.triage(text, location)
        latency_ms = self._elapsed_ms(started)

        logger.warning(
            "triage fell back to rules",
            extra={
                "provider": self._provider.name,
                "error_class": type(exc).__name__,
                "error": str(exc)[:200],
                "latency_ms": latency_ms,
                "request_id": request_id,
            },
        )

        # Deliberately NOT cached: caching a degraded classification would keep serving it
        # for 24h after the provider recovered.
        decision = TriageDecision(
            result=result,
            triaged_by=TriagedBy.RULES_FALLBACK,
            latency_ms=latency_ms,
            fallback=True,
            cached=False,
        )
        self._record(decision, request_id)
        return decision

    def _triaged_by_for(self, provider_name: str) -> TriagedBy:
        return _PROVIDER_TO_TRIAGED_BY.get(provider_name, TriagedBy.RULES)

    def _elapsed_ms(self, started: float) -> int:
        return max(int((time.perf_counter() - started) * 1000), 0)

    def _record(self, decision: TriageDecision, request_id: str | None) -> None:
        self._recent.append(
            TriageOutcome(
                complaint_id=None,  # attached by the complaint service once the row exists
                provider=(
                    TriagedBy.RULES_FALLBACK.value if decision.fallback else self._provider.name
                ),
                latency_ms=decision.latency_ms,
                fallback=decision.fallback,
                cached=decision.cached,
                at=datetime.now(UTC),
            )
        )

    def attach_complaint_id(self, complaint_id: uuid.UUID) -> None:
        """Backfill the id onto the outcome just recorded, so /api/meta/providers can be
        traced back to a specific complaint."""
        if self._recent:
            self._recent[-1] = self._recent[-1].model_copy(update={"complaint_id": complaint_id})

    def cache_stats(self) -> tuple[int, int, float]:
        return self._cache.triage_hits, self._cache.triage_misses, self._cache.triage_hit_rate
