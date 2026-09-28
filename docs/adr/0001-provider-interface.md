# ADR 0001 — The triage provider interface

- **Status:** accepted
- **Date:** 2026-09-28
- **Deciders:** Muhammad Ammar Yasar

## Context

A citizen's complaint arrives as free text. Something has to read it and decide a category, a
priority and a one-line summary.

The brief is explicit that the reading is not the engineering problem (§1.1): the reader must be
**replaceable**. Today it is a keyword rule, tomorrow a hosted language model, next year a
fine-tuned classifier. Whatever it is, it will sometimes be slow, rate-limited, or confidently
wrong, and the system must not fall over when it is.

So the decision is not "which model". It is "what shape of seam lets the model be swapped, and
lets the system survive the model failing".

## Decision

Define a single structural interface and put every reader behind it.

```python
class TriageProvider(Protocol):
    name: str
    def triage(self, text: str, location: str) -> TriageResult: ...
```

Four implementations, selected at startup by the `TRIAGE_PROVIDER` environment variable:

| Provider | Role |
|---|---|
| `LLMTriage` | Production. A free-tier hosted model (Groq), OpenAI-compatible endpoint. |
| `OllamaTriage` | Fully offline. A container in the Compose stack. No key, no egress. |
| `RuleBasedTriage` | Deterministic keywords. Always available, never fails. The floor. |
| `SimulatedTriage` | Seeded fake for CI. No network, configurable failure injection. |

Three specific choices within that:

**A `Protocol`, not an abstract base class.** A provider does not have to inherit from us to satisfy
the seam, which makes the test doubles in `backend/tests/fakes.py` three-line classes rather than
subclasses carrying machinery they do not need. Structural typing is the lighter contract, and
`mypy` still enforces it.

**The orchestrator is separate from the providers.** `TriageService`
(`backend/app/services/triage_service.py`) owns the cache lookup, the timeout, the single jittered
retry, the fallback and the latency measurement. A provider only knows how to make one call and
either return a `TriageResult` or raise a typed error. This is the division that matters: adding a
fifth provider does not touch any resilience logic, and changing the retry policy does not touch any
provider.

**`triage()` never raises.** This is the invariant every layer above depends on. The provider may
raise anything; the service catches it, falls back to rules, records
`triaged_by = "rules:fallback"` and returns a usable result. A third party having a bad day cannot
become a citizen's HTTP 500.

## Consequences

**What this buys.**

- Swapping the reader is an env var, and CI pins it to `simulated` so the suite is deterministic
  while production runs a probabilistic model (§2.5).
- Failure modes are testable without a network: inject a provider that always raises to exercise the
  fallback, one that returns malformed JSON to exercise the validator.
- `triaged_by` is persisted per complaint, so the operations dashboard shows which reader classified
  each row — and a run of `rules:fallback` is visible without reading a log.

**What it costs.**

- Four implementations to keep working, of which two are not production paths.
- The `Protocol` is enforced at type-check time only. A provider that satisfies the signature but
  returns nonsense passes; that is what `TriageResult` validation is for.
- Latency is measured at the orchestrator, so it includes the retry. A cache hit is recorded as 0 ms
  by choice, because attributing real time to it would pollute the series used to reason about
  inference cost.

## Alternatives considered

**Call the LLM directly from the route.** Rejected: four lines of code that puts an unbounded
third-party call on the request path with no timeout, no fallback and no way to test the route
without a network. It also spreads provider knowledge into the HTTP layer.

**Inherit from an ABC.** Workable, and marginally more discoverable. Rejected because it forces test
doubles to inherit and makes the seam nominal rather than structural for no benefit.

**A queue: accept the complaint, triage asynchronously.** This is the right answer at scale, and it
is what I would build for real traffic — it removes the LLM from the request path entirely. Rejected
here because the brief requires the submit response to return the category, priority and summary
(§2.1), which implies synchronous triage; and because introducing a broker and a worker would add a
sixth container for no marks. The 10-second hard timeout is what makes synchronous acceptable.

**Let the citizen pick a category from a dropdown.** The naive fix the brief dismisses, correctly:
citizens pick wrong, pick "Other" to get through the form, and cannot judge urgency (§1.1).

## Related

- [ADR 0004](0004-pii-and-data-governance.md) — what leaves the machine when `LLMTriage` is active.
- `docs/TRIAGE.md` — measured comparison of the providers on the same inputs.
