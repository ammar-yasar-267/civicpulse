"""The triage seam.

The whole system is built so the thing that reads a complaint is replaceable (§1.1).
Everything upstream of this module depends on TriageProvider and nothing else — not on
Groq, not on Ollama, not on a keyword table. Swapping the reader is an env var.
"""

from typing import Protocol, runtime_checkable

from app.schemas import TriageResult


@runtime_checkable
class TriageProvider(Protocol):
    """Structural interface, as given in §2.5.

    A Protocol rather than an ABC deliberately: a provider does not have to inherit from
    us to satisfy the seam, which is what makes the test doubles in tests/ one-liners.
    """

    name: str

    def triage(self, text: str, location: str) -> TriageResult: ...


class TriageError(Exception):
    """Base for provider failures. The orchestrator treats these as 'the clever reader
    failed' and falls back to rules — a third party's bad day is never a user's 500."""


class TriageTimeout(TriageError):
    """Provider exceeded the hard timeout cap."""


class TriageRateLimited(TriageError):
    """Provider returned 429. Retryable, once, with jitter."""


class TriageUpstreamError(TriageError):
    """Provider returned 5xx. Retryable, once, with jitter."""


class TriageBadRequest(TriageError):
    """Provider returned 4xx other than 429. NOT retryable — the request was wrong and
    will be wrong again (§2.5 rule 3)."""


class TriageMalformedOutput(TriageError):
    """Provider replied, but the payload failed TriageResult validation: prose, a code
    fence, an invented category, a 400-character 'one-line' summary. Not retryable."""
