"""SQLAlchemy ORM models.

The table is created by Alembic migrations only — there is no create_all() anywhere in
startup code (§2.3). This metadata is what Alembic autogenerates against.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import Category, Priority, Status, TriagedBy


class Base(DeclarativeBase):
    pass


def _pg_enum(enum_cls: type, name: str) -> SAEnum:
    """Native PG enum storing the *values* (lowercase) rather than the python names."""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
    )


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    reporter_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)

    category: Mapped[Category] = mapped_column(_pg_enum(Category, "category"), nullable=False)
    priority: Mapped[Priority] = mapped_column(_pg_enum(Priority, "priority"), nullable=False)
    status: Mapped[Status] = mapped_column(
        _pg_enum(Status, "status"), nullable=False, server_default=Status.OPEN.value
    )

    ai_summary: Mapped[str | None] = mapped_column(String(140), nullable=True)
    triaged_by: Mapped[TriagedBy] = mapped_column(_pg_enum(TriagedBy, "triaged_by"), nullable=False)
    triage_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Natural key for the idempotent seed: a stable hash of the seeded content.
    # NULL for citizen-submitted rows, so real duplicates are still allowed through.
    seed_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Length limits enforced in the DB as well as the app (§2.3): the API is not the
        # only writer — the seed script and any future consumer hit the same constraint.
        CheckConstraint("char_length(text) BETWEEN 10 AND 2000", name="ck_complaints_text_len"),
        CheckConstraint(
            "char_length(location) BETWEEN 3 AND 200", name="ck_complaints_location_len"
        ),
        CheckConstraint("char_length(ai_summary) <= 140", name="ck_complaints_summary_len"),
        CheckConstraint("triage_latency_ms >= 0", name="ck_complaints_latency_nonneg"),
        # Serves the dashboard's default filter+sort (see docs/ENGINEERING-NOTES.md Q on indexes).
        Index("ix_complaints_status_priority", "status", "priority"),
        # Serves "newest first" pagination and the created_at range in /api/stats.
        Index("ix_complaints_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Complaint {self.id} {self.category}/{self.priority} {self.status}>"
