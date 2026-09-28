"""Pydantic v2 schemas.

One validation mental model, two uses (§2.2): these types validate untrusted HTTP input
*and* untrusted LLM output. TriageResult is the contract in §2.5 and is the reason a
model that returns a category outside our enum fails closed instead of reaching the DB.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Category, Priority, Status, TriagedBy

# --- the AI contract (§2.5, given in the brief) ---------------------------------


class TriageResult(BaseModel):
    category: Category
    priority: Priority
    summary: str = Field(max_length=140)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary")
    @classmethod
    def _one_line(cls, v: str) -> str:
        """A 'one-line summary' with newlines in it is not one line. Collapse rather than
        reject: the content is usable, the shape is not."""
        collapsed = " ".join(v.split())
        if not collapsed:
            raise ValueError("summary must not be empty")
        return collapsed


# --- complaint I/O --------------------------------------------------------------


class ComplaintCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=10, max_length=2000)
    location: str = Field(min_length=3, max_length=200)
    reporter_contact: str | None = Field(default=None, max_length=200)


class ComplaintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    location: str
    reporter_contact: str | None
    category: Category
    priority: Priority
    status: Status
    ai_summary: str | None
    triaged_by: TriagedBy
    triage_latency_ms: int
    created_at: datetime
    updated_at: datetime


class StatusUpdate(BaseModel):
    status: Status


class Page(BaseModel):
    """Envelope for GET /api/complaints — 'total' is required by the contract so the
    frontend can render a real pager rather than guessing at the last page."""

    items: list[ComplaintOut]
    total: int
    page: int
    page_size: int


# --- stats ---------------------------------------------------------------------


class Stats(BaseModel):
    total: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    by_status: dict[str, int]
    generated_at: datetime


# --- observability surface (§2.2 GET /api/meta/providers) -----------------------


class TriageOutcome(BaseModel):
    complaint_id: uuid.UUID | None = None
    provider: str
    latency_ms: int
    fallback: bool
    cached: bool = False
    at: datetime


class ProvidersMeta(BaseModel):
    active_provider: str
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    recent_outcomes: list[TriageOutcome]


# --- errors --------------------------------------------------------------------


class FieldError(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    """Field-level error body for 400s (§2.2). A flat 'detail' string would force the
    frontend to parse prose to highlight the offending input."""

    error: str
    detail: str
    fields: list[FieldError] = Field(default_factory=list)


class ReadyBody(BaseModel):
    status: str
    dependencies: dict[str, str]
    failed: str | None = None
