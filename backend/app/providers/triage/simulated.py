"""Deterministic fake provider — the one CI runs (§2.5 "Determinism").

Why this exists: with TRIAGE_PROVIDER=llm the same input can produce different output, and
a test suite that is green only on average trains a team to ignore red. This provider is
seeded from a hash of the input, so the same complaint always classifies the same way, with
no network and no key. CI pins TRIAGE_PROVIDER=simulated.

It also injects failures on demand, which is how the fallback and validator paths are
tested without waiting for a real provider to misbehave:
  SIMULATED_FAILURE_EVERY=1    every call raises            -> exercises rules:fallback
  SIMULATED_MALFORMED_EVERY=1  every call returns bad JSON  -> exercises the validator
"""

import hashlib
from itertools import count

from app.config import Settings
from app.domain.enums import Category, Priority
from app.providers.triage.base import TriageUpstreamError
from app.providers.triage.prompt import parse_triage_response
from app.providers.triage.rules import RuleBasedTriage
from app.schemas import TriageResult

# Annotated explicitly: iterating a StrEnum otherwise infers as list[str], and the enum type
# is what TriageResult expects.
_CATEGORIES: list[Category] = list(Category)
_PRIORITIES: list[Priority] = list(Priority)


class SimulatedTriage:
    """Seeded, no network, configurable failure injection."""

    name = "simulated"

    def __init__(self, settings: Settings) -> None:
        self._failure_every = max(0, settings.simulated_failure_every)
        self._malformed_every = max(0, settings.simulated_malformed_every)
        self._calls = count(1)
        # Borrows the keyword reader so simulated output is plausible rather than random:
        # a water complaint classifies as water, which keeps assertions in the integration
        # tests meaningful instead of tautological.
        self._rules = RuleBasedTriage()

    def _seed(self, text: str, location: str) -> int:
        digest = hashlib.sha256(f"{text}|{location}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    def triage(self, text: str, location: str) -> TriageResult:
        call_number = next(self._calls)

        if self._failure_every and call_number % self._failure_every == 0:
            raise TriageUpstreamError("simulated provider failure (injected)")

        if self._malformed_every and call_number % self._malformed_every == 0:
            # Exactly the shape a real model eventually produces: a code fence wrapped
            # around a category that is not in our enum.
            return parse_triage_response(
                '```json\n{"category": "plumbing", "priority": "urgent", '
                '"summary": "not a real category", "confidence": 1.5}\n```'
            )

        base = self._rules.triage(text, location)
        seed = self._seed(text, location)

        # If the keyword reader found nothing, pick deterministically from the seed so the
        # fake still covers every category across a seeded dataset.
        category = base.category
        if category is Category.OTHER:
            category = _CATEGORIES[seed % len(_CATEGORIES)]
        priority = base.priority if base.confidence >= 0.6 else _PRIORITIES[seed % len(_PRIORITIES)]

        return TriageResult(
            category=category,
            priority=priority,
            summary=base.summary,
            # Stable pseudo-confidence in [0.70, 0.99] — never 1.0, because a classifier
            # claiming certainty is a smell even in a fake.
            confidence=round(0.70 + (seed % 30) / 100, 2),
        )
