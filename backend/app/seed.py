"""Idempotent seed command (§2.3).

    python -m app.seed          # insert what is missing
    python -m app.seed --force  # re-triage and overwrite existing seeded rows

Idempotency is enforced by the database, not by the script: each row carries a seed_key that
is a hash of its content, and seed_key has a UNIQUE constraint. A second run finds the key
and skips. Checking "is the table empty?" instead would be wrong — it breaks the moment a
citizen submits one complaint, and it cannot add new seed entries to an existing dataset.

Rows are triaged by the configured provider, so the seed exercises the real triage path. With
TRIAGE_PROVIDER=rules (the default) it needs no key and no network.
"""

import argparse
import hashlib
import logging
import sys

from app.config import get_settings
from app.db import build_engine, build_session_factory, session_scope
from app.domain.enums import Status
from app.logging_setup import configure_logging
from app.providers.cache import CacheProvider, build_redis_client
from app.providers.triage.factory import build_provider
from app.repositories.complaints import ComplaintRepository
from app.seed_data import SEED_COMPLAINTS
from app.services.triage_service import TriageService

logger = logging.getLogger("app.seed")


def seed_key_for(text: str, location: str) -> str:
    """Stable natural key for a seeded row. Content-derived, so editing a seed entry's text
    makes it a new row rather than silently diverging from the corpus."""
    return hashlib.sha256(f"seed|{text}|{location}".encode()).hexdigest()


def run_seed(force: bool = False) -> tuple[int, int]:
    """Returns (inserted, skipped)."""
    settings = get_settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)

    redis_client = build_redis_client(settings.redis_url)
    cache = CacheProvider(redis_client)
    triage = TriageService(build_provider(settings), cache, settings)

    inserted = 0
    skipped = 0

    with session_scope(session_factory) as session:
        repo = ComplaintRepository(session)

        for text, location, contact, status in SEED_COMPLAINTS:
            key = seed_key_for(text, location)
            existing = repo.get_by_seed_key(key)

            if existing is not None and not force:
                skipped += 1
                continue

            decision = triage.triage(text, location)

            if existing is not None:
                existing.category = decision.result.category
                existing.priority = decision.result.priority
                existing.ai_summary = decision.result.summary
                existing.triaged_by = decision.triaged_by
                existing.triage_latency_ms = decision.latency_ms
                inserted += 1
                continue

            complaint = repo.create(
                text=text,
                location=location,
                reporter_contact=contact,
                category=decision.result.category,
                priority=decision.result.priority,
                ai_summary=decision.result.summary,
                triaged_by=decision.triaged_by,
                triage_latency_ms=decision.latency_ms,
                seed_key=key,
            )
            # Statuses are set directly rather than walked through the state machine: the
            # seed is fabricating history, not operating the system, and the machine's job
            # is to police live transitions.
            if status is not Status.OPEN:
                complaint.status = status
            inserted += 1

    # The aggregates just changed underneath any cached copy.
    cache.invalidate_stats()
    engine.dispose()
    redis_client.close()

    return inserted, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CivicPulse with realistic complaints.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-triage and overwrite rows that were already seeded.",
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    inserted, skipped = run_seed(force=args.force)

    logger.info(
        "seed complete",
        extra={
            "inserted_or_updated": inserted,
            "skipped_already_present": skipped,
            "corpus_size": len(SEED_COMPLAINTS),
        },
    )
    print(
        f"seed: {inserted} inserted/updated, {skipped} already present "
        f"({len(SEED_COMPLAINTS)} in corpus)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
