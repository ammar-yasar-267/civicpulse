"""Shared fixtures.

Two deliberate choices:

* Postgres is real. The schema under test is created by running the actual Alembic migration
  (`upgrade head`), so the migration is exercised on every run rather than trusted. SQLite
  would not do: the schema relies on native enums, gen_random_uuid() and char_length CHECK
  constraints, and a test suite that passes against a database you do not deploy is theatre.
* Redis is faked. Its behaviour is fully specified by the few commands we use, and faking it
  makes TTL expiry testable by advancing a clock instead of sleeping.

The test database is a throwaway container on port 55432, started by
`scripts/test-db.sh up` locally and by a service container in CI. If it is unreachable the
DB-backed tests skip with an explanatory message instead of failing mysteriously.
"""

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.enums import Category, Priority
from app.providers.cache import CacheProvider
from app.providers.ratelimit import RateLimiter
from app.providers.triage.rules import RuleBasedTriage
from app.schemas import TriageResult
from app.services.triage_service import TriageService
from tests.fakes import FakeClock, FakeRedis

TEST_DB_PORT = int(os.environ.get("TEST_POSTGRES_PORT", "55432"))
TEST_DB_HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Settings pointed at the throwaway database, with triage pinned to the deterministic
    keyword reader so no test can depend on a network call."""
    return Settings(
        postgres_host=TEST_DB_HOST,
        postgres_port=TEST_DB_PORT,
        postgres_user=os.environ.get("TEST_POSTGRES_USER", "civicpulse"),
        postgres_password=os.environ.get("TEST_POSTGRES_PASSWORD", "civicpulse"),
        postgres_db=os.environ.get("TEST_POSTGRES_DB", "civicpulse_test"),
        triage_provider="rules",
        stats_cache_ttl_seconds=30,
        rate_limit_requests=5,
        rate_limit_window_seconds=60,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def engine(test_settings: Settings) -> Iterator[Engine]:
    """Session-scoped engine with the migration applied once."""
    eng = build_engine(test_settings)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(
            f"Test Postgres unavailable on {TEST_DB_HOST}:{TEST_DB_PORT} ({type(exc).__name__}). "
            "Start it with: scripts/test-db.sh up",
            allow_module_level=False,
        )

    _run_migrations(test_settings)
    yield eng
    eng.dispose()


def _run_migrations(settings: Settings) -> None:
    """Apply the real migration chain — downgrade to base first, so a re-run starts clean and
    the downgrade path is exercised too."""
    from alembic import command
    from alembic.config import Config

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Nothing to undo on a fresh database, so a failed downgrade is expected there.
    with contextlib.suppress(Exception):
        command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
def clean_db(engine: Engine) -> Iterator[None]:
    """Truncate between tests. Faster than re-migrating and keeps tests order-independent —
    a suite that only passes in one order is not a suite."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE complaints"))
    yield


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_redis(fake_clock: FakeClock) -> FakeRedis:
    return FakeRedis(fake_clock)


@pytest.fixture
def cache(fake_redis: FakeRedis) -> CacheProvider:
    return CacheProvider(fake_redis)  # type: ignore[arg-type]


@pytest.fixture
def triage_service(cache: CacheProvider, test_settings: Settings) -> TriageService:
    return TriageService(RuleBasedTriage(), cache, test_settings)


@pytest.fixture
def app(
    engine: Engine,
    clean_db: None,
    test_settings: Settings,
    cache: CacheProvider,
    fake_redis: FakeRedis,
    triage_service: TriageService,
) -> FastAPI:
    """The real application object with real routes, middleware and exception handlers.

    Built directly rather than through lifespan so the fakes can be injected onto app.state:
    this is integration testing of our own layers, with only the two external systems
    substituted.
    """
    from app.main import create_app

    application = create_app()
    application.router.lifespan_context = _null_lifespan  # type: ignore[assignment]

    application.state.settings = test_settings
    application.state.engine = engine
    application.state.session_factory = build_session_factory(engine)
    application.state.cache = cache
    application.state.rate_limiter = RateLimiter(
        fake_redis,  # type: ignore[arg-type]
        limit=test_settings.rate_limit_requests,
        window_seconds=test_settings.rate_limit_window_seconds,
    )
    application.state.triage_service = triage_service
    return application


def _null_lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield

    return _noop(app)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def unlimited_client(app: FastAPI, fake_redis: FakeRedis) -> Iterator[TestClient]:
    """Client with a generous rate limit, for tests that post several complaints and are not
    themselves about rate limiting."""
    app.state.rate_limiter = RateLimiter(fake_redis, limit=1000, window_seconds=60)  # type: ignore[arg-type]
    with TestClient(app) as test_client:
        yield test_client


# --- data helpers --------------------------------------------------------------


def sample_result(
    category: Category = Category.WATER,
    priority: Priority = Priority.HIGH,
    summary: str = "Street 12: burst main flooding ground floors",
    confidence: float = 0.9,
) -> TriageResult:
    return TriageResult(
        category=category, priority=priority, summary=summary, confidence=confidence
    )


def valid_payload(**overrides: object) -> dict:
    payload = {
        "text": "Burst water main flooding Street 12 since fajr, water entering ground floors.",
        "location": "Street 12, Gulberg III, Lahore",
        "reporter_contact": "0300-1234567",
    }
    payload.update(overrides)  # type: ignore[arg-type]
    return payload


def unique_payload(**overrides: object) -> dict:
    """Distinct content per call, so the triage content-hash cache does not make two
    logically separate submissions share one cached classification."""
    marker = uuid.uuid4().hex[:8]
    payload = valid_payload(
        text=f"Garbage not lifted for ten days near corner point, ref {marker}, smell is bad."
    )
    payload.update(overrides)  # type: ignore[arg-type]
    return payload
