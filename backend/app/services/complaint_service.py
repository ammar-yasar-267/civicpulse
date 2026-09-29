"""Complaint business rules (§2.2 services layer).

Owns the triage-then-persist orchestration and the state machine gate. Knows nothing about
HTTP status codes — it raises domain exceptions and lets the route translate them, which is
what keeps the rules reusable by the seed script and any future CLI.
"""

import logging
import uuid
from datetime import datetime

from app.domain.enums import Category, Priority, Status
from app.domain.state_machine import assert_transition
from app.models import Complaint
from app.providers.cache import CacheProvider
from app.repositories.complaints import ComplaintRepository
from app.schemas import ComplaintCreate
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)


class ComplaintNotFound(Exception):
    def __init__(self, complaint_id: uuid.UUID) -> None:
        self.complaint_id = complaint_id
        super().__init__(f"Complaint {complaint_id} not found")


class ComplaintService:
    def __init__(
        self,
        repository: ComplaintRepository,
        triage: TriageService,
        cache: CacheProvider,
    ) -> None:
        self._repo = repository
        self._triage = triage
        self._cache = cache

    def submit(self, payload: ComplaintCreate, request_id: str | None = None) -> Complaint:
        """Validate (done by Pydantic) -> triage -> persist.

        Triage happens before the insert so the row is never written in an untriaged state
        that something else would have to reconcile later. It is safe to do this on the
        request path only because TriageService cannot raise and is hard-capped at 10s.
        """
        decision = self._triage.triage(payload.text, payload.location, request_id=request_id)

        complaint = self._repo.create(
            text=payload.text,
            location=payload.location,
            reporter_contact=payload.reporter_contact,
            category=decision.result.category,
            priority=decision.result.priority,
            ai_summary=decision.result.summary,
            triaged_by=decision.triaged_by,
            triage_latency_ms=decision.latency_ms,
        )

        self._triage.attach_complaint_id(complaint.id)

        # A new complaint changes every aggregate, so drop the cached stats now rather than
        # letting a citizen watch a dashboard that disagrees with their own submission for
        # the next 30 seconds (§2.4).
        self._cache.invalidate_stats()

        logger.info(
            "complaint submitted",
            extra={
                "complaint_id": str(complaint.id),
                "category": complaint.category.value,
                "priority": complaint.priority.value,
                "triaged_by": complaint.triaged_by.value,
                "triage_latency_ms": complaint.triage_latency_ms,
                "triage_cached": decision.cached,
                "request_id": request_id,
            },
        )
        return complaint

    def get(self, complaint_id: uuid.UUID) -> Complaint:
        complaint = self._repo.get(complaint_id)
        if complaint is None:
            raise ComplaintNotFound(complaint_id)
        return complaint

    def list_page(
        self,
        *,
        page: int,
        page_size: int,
        category: Category | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[list[Complaint], int]:
        return self._repo.list_page(
            page=page,
            page_size=page_size,
            category=category,
            priority=priority,
            status=status,
            created_after=created_after,
            created_before=created_before,
        )

    def change_status(
        self,
        complaint_id: uuid.UUID,
        requested: Status,
        request_id: str | None = None,
    ) -> Complaint:
        """Gate the move through the transition table, then persist.

        Raises ComplaintNotFound (-> 404) or InvalidTransition (-> 409 naming the attempted
        transition). The route does the mapping; this layer stays HTTP-agnostic.
        """
        complaint = self.get(complaint_id)
        previous = complaint.status

        assert_transition(previous, requested)

        updated = self._repo.update_status(complaint, requested)
        self._cache.invalidate_stats()  # by_status aggregates just changed

        logger.info(
            "complaint status changed",
            extra={
                "complaint_id": str(updated.id),
                "from_status": previous.value,
                "to_status": requested.value,
                "request_id": request_id,
            },
        )
        return updated
