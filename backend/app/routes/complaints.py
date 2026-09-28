"""Complaint endpoints. HTTP only (§2.2): parse, validate, serialise, status codes.

No business rule and no SQL appears in this file. The state machine lives in
app/domain/state_machine.py and is enforced by the service; this layer's only job is to turn
InvalidTransition into a 409 whose body names the attempted transition.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.dependencies import ComplaintServiceDep, RateLimiterDep, SettingsDep
from app.domain.enums import Category, Priority, Status
from app.domain.state_machine import InvalidTransition
from app.logging_setup import get_request_id
from app.providers.ratelimit import client_identifier
from app.schemas import ComplaintCreate, ComplaintOut, ErrorBody, Page, StatusUpdate
from app.services.complaint_service import ComplaintNotFound

router = APIRouter(prefix="/api/complaints", tags=["complaints"])


def enforce_rate_limit(
    request: Request,
    response: Response,
    limiter: RateLimiterDep,
) -> None:
    """Distributed limiter on the write path (§2.4 job 2).

    Guards the LLM quota: one bored user with a for-loop would otherwise exhaust a day's
    free tier. 429 carries Retry-After so a well-behaved client knows when to return.
    """
    identifier = client_identifier(
        request.client.host if request.client else None,
        request.headers.get("X-Forwarded-For"),
    )
    decision = limiter.check(identifier)

    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)

    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limited",
                "detail": (
                    f"Rate limit of {decision.limit} requests exceeded. "
                    f"Retry in {decision.retry_after_seconds}s."
                ),
                "fields": [],
            },
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )


@router.post(
    "",
    response_model=ComplaintOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_rate_limit)],
    responses={
        400: {"model": ErrorBody, "description": "Field-level validation error"},
        429: {"model": ErrorBody, "description": "Rate limit exceeded; see Retry-After"},
    },
)
def submit_complaint(
    payload: ComplaintCreate,
    service: ComplaintServiceDep,
) -> ComplaintOut:
    """Validate -> triage -> persist. 201 with the triaged row.

    Never 500s because triage failed: the service falls back to rules and records
    triaged_by = "rules:fallback" (§2.5 rule 4).
    """
    complaint = service.submit(payload, request_id=get_request_id())
    return ComplaintOut.model_validate(complaint)


@router.get("", response_model=Page)
def list_complaints(
    service: ComplaintServiceDep,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category: Category | None = None,
    priority: Priority | None = None,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
) -> Page:
    """Filter by category, priority and status; paginate; return the total.

    page_size is capped at 100 by the Query constraint, so a caller cannot ask for the whole
    table and turn pagination into a denial of service.
    """
    page_size = min(page_size, settings.max_page_size)
    items, total = service.list_page(
        page=page,
        page_size=page_size,
        category=category,
        priority=priority,
        status=status_filter,
    )
    return Page(
        items=[ComplaintOut.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{complaint_id}",
    response_model=ComplaintOut,
    responses={404: {"model": ErrorBody, "description": "Not found"}},
)
def get_complaint(complaint_id: uuid.UUID, service: ComplaintServiceDep) -> ComplaintOut:
    try:
        complaint = service.get(complaint_id)
    except ComplaintNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "detail": f"Complaint {exc.complaint_id} not found.",
                "fields": [],
            },
        ) from exc
    return ComplaintOut.model_validate(complaint)


@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintOut,
    responses={
        404: {"model": ErrorBody, "description": "Not found"},
        409: {"model": ErrorBody, "description": "Invalid status transition"},
    },
)
def update_status(
    complaint_id: uuid.UUID,
    payload: StatusUpdate,
    service: ComplaintServiceDep,
) -> ComplaintOut:
    """Enforce the state machine. An illegal move is a 409 that names the transition, which
    the operator UI surfaces verbatim rather than as a generic "error"."""
    try:
        complaint = service.change_status(complaint_id, payload.status, request_id=get_request_id())
    except ComplaintNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "detail": f"Complaint {exc.complaint_id} not found.",
                "fields": [],
            },
        ) from exc
    except InvalidTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_transition",
                "detail": exc.message,
                "fields": [
                    {"field": "status", "message": exc.message},
                ],
            },
        ) from exc
    return ComplaintOut.model_validate(complaint)
