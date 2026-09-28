"""Provider selection — the one place that knows which implementations exist.

Everything else depends on the TriageProvider protocol (§2.5). Adding a fifth provider
touches this file and nothing else, which is the abstraction actually paying rent rather
than being asserted in a README.
"""

import logging

from app.config import Settings
from app.providers.triage.base import TriageProvider
from app.providers.triage.llm import LLMTriage, OllamaTriage
from app.providers.triage.rules import RuleBasedTriage
from app.providers.triage.simulated import SimulatedTriage

logger = logging.getLogger(__name__)


def build_provider(settings: Settings) -> TriageProvider:
    """Construct the provider named by TRIAGE_PROVIDER.

    A misconfigured hosted provider degrades to rules rather than refusing to boot: the
    alternative is a pod that crash-loops because somebody forgot a key, which turns a
    triage-quality problem into a total outage.
    """
    choice = settings.triage_provider

    if choice == "llm":
        try:
            return LLMTriage(settings)
        except ValueError as exc:
            logger.warning(
                "triage provider misconfigured, degrading to rules",
                extra={"requested_provider": choice, "error": str(exc)},
            )
            return RuleBasedTriage()

    if choice == "ollama":
        return OllamaTriage(settings)
    if choice == "simulated":
        return SimulatedTriage(settings)
    return RuleBasedTriage()


def build_fallback() -> RuleBasedTriage:
    """The floor. Always available, never fails, no configuration (§2.5 rule 4)."""
    return RuleBasedTriage()
