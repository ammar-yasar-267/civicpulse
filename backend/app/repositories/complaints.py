"""Complaint persistence. All SQL lives here and nowhere else (§2.2).

The rule is worth stating precisely: no other layer may import sqlalchemy query
constructs. Routes do HTTP, services decide, this file is the only thing that knows there
is a database at all — which is why swapping the store would touch one directory.
"""

import uuid
from datetime import UTC, datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.domain.enums import Category, Priority, Status, TriagedBy
from app.models import Complaint


class ComplaintRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes ----------------------------------------------------------------

    def create(
        self,
        *,
        text: str,
        location: str,
        reporter_contact: str | None,
        category: Category,
        priority: Priority,
        ai_summary: str | None,
        triaged_by: TriagedBy,
        triage_latency_ms: int,
        seed_key: str | None = None,
    ) -> Complaint:
        complaint = Complaint(
            text=text,
            location=location,
            reporter_contact=reporter_contact,
            category=category,
            priority=priority,
            status=Status.OPEN,
            ai_summary=ai_summary,
            triaged_by=triaged_by,
            triage_latency_ms=triage_latency_ms,
            seed_key=seed_key,
        )
        self._session.add(complaint)
        self._session.flush()  # assign the server-side id without ending the transaction
        self._session.refresh(complaint)
        return complaint

    def update_status(self, complaint: Complaint, status: Status) -> Complaint:
        complaint.status = status
        complaint.updated_at = datetime.now(UTC)
        self._session.flush()
        return complaint

    # --- reads -----------------------------------------------------------------

    def get(self, complaint_id: uuid.UUID) -> Complaint | None:
        return self._session.get(Complaint, complaint_id)

    def get_by_seed_key(self, seed_key: str) -> Complaint | None:
        return self._session.scalar(select(Complaint).where(Complaint.seed_key == seed_key))

    def _filtered(
        self,
        category: Category | None,
        priority: Priority | None,
        status: Status | None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> Select:
        stmt = select(Complaint)
        if category is not None:
            stmt = stmt.where(Complaint.category == category)
        if priority is not None:
            stmt = stmt.where(Complaint.priority == priority)
        if status is not None:
            stmt = stmt.where(Complaint.status == status)
        if created_after is not None:
            # Normalise naive datetimes to UTC so comparisons are always tz-aware.
            if created_after.tzinfo is None:
                created_after = created_after.replace(tzinfo=timezone.utc)
            stmt = stmt.where(Complaint.created_at >= created_after)
        if created_before is not None:
            if created_before.tzinfo is None:
                created_before = created_before.replace(tzinfo=timezone.utc)
            stmt = stmt.where(Complaint.created_at <= created_before)
        return stmt

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
        """One page plus the unpaginated total, which the contract requires so the UI can
        render a real pager.

        Ordering is created_at DESC, id DESC. The id tiebreak is not decoration: two rows
        seeded in the same transaction share a timestamp, and without it their relative
        order can differ between pages and silently drop or duplicate a row.

        Query served by ix_complaints_status_priority (filter) and
        ix_complaints_created_at (sort and date-range filter) — see docs/ENGINEERING-NOTES.md.
        """
        base = self._filtered(category, priority, status, created_after, created_before)

        total = self._session.scalar(select(func.count()).select_from(base.subquery()))

        stmt = (
            base.order_by(Complaint.created_at.desc(), Complaint.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self._session.scalars(stmt).all())
        return items, int(total or 0)

    # --- aggregates ------------------------------------------------------------

    def counts_by(self, column: str) -> dict[str, int]:
        col = {
            "category": Complaint.category,
            "priority": Complaint.priority,
            "status": Complaint.status,
        }[column]
        rows = self._session.execute(select(col, func.count()).group_by(col)).all()
        return {str(getattr(value, "value", value)): int(count) for value, count in rows}

    def total(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(Complaint)) or 0)
