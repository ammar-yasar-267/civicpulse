"""FastAPI dependency wiring — the composition root.

This is the only module that knows how the layers are assembled. Routes ask for a service;
they never construct a repository, open a session or touch the engine. A route that opens a
database session is a design failure worth marks (§2.2), and the way to make that hard is to
give routes no way to get one.

Long-lived objects (engine, redis client, provider, TriageService) hang off app.state and are
built once at startup. Per-request objects (session, repository, services) are created per
request and torn down by FastAPI's dependency teardown.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.providers.cache import CacheProvider
from app.providers.ratelimit import RateLimiter
from app.repositories.complaints import ComplaintRepository
from app.services.complaint_service import ComplaintService
from app.services.stats_service import StatsService
from app.services.triage_service import TriageService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cache(request: Request) -> CacheProvider:
    return request.app.state.cache


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_triage_service(request: Request) -> TriageService:
    return request.app.state.triage_service


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, committed on success, rolled back on any exception.

    yield + try/finally rather than a context manager in each route: the teardown runs even
    if the route raises, so a failed request cannot leak a pooled connection.
    """
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
CacheDep = Annotated[CacheProvider, Depends(get_cache)]
TriageDep = Annotated[TriageService, Depends(get_triage_service)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def get_repository(session: SessionDep) -> ComplaintRepository:
    return ComplaintRepository(session)


RepositoryDep = Annotated[ComplaintRepository, Depends(get_repository)]


def get_complaint_service(
    repository: RepositoryDep,
    triage: TriageDep,
    cache: CacheDep,
) -> ComplaintService:
    return ComplaintService(repository, triage, cache)


def get_stats_service(
    repository: RepositoryDep,
    cache: CacheDep,
    settings: SettingsDep,
) -> StatsService:
    return StatsService(repository, cache, settings)


ComplaintServiceDep = Annotated[ComplaintService, Depends(get_complaint_service)]
StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]
