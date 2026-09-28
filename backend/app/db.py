"""Engine and session plumbing.

No create_all() here or anywhere else in startup code — the schema is Alembic's job (§2.3).
A migration is a versioned, reviewable, reversible change; a startup script is a hope.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        # Small pool per pod, sized against Postgres's ~100 connection default: ten pods
        # x (5 + 5 overflow) already approaches it, which is exactly the arithmetic that
        # surprises people the first time an HPA scales out.
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        # Recycle below any proxy/idle timeout so a pooled connection is never handed out
        # already dead after a quiet night.
        pool_recycle=1800,
        pool_pre_ping=True,
        future=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transaction per unit of work: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_reachable(engine: Engine) -> bool:
    """Used by /ready only. SELECT 1 is a real round-trip to Postgres, which is the point:
    readiness must mean "I can serve traffic", not "my process started"."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
