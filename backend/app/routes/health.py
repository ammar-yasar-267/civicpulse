"""Liveness, readiness and metrics.

/health and /ready are separate because Kubernetes uses them for different decisions
(§2.2), and wiring them backwards is a self-inflicted outage:

  livenessProbe  -> /health -> failing RESTARTS the pod.
                    Therefore it MUST NOT touch Postgres or Redis. If it did, a slow
                    database would restart every backend pod simultaneously, and a restart
                    loop across the whole deployment is strictly worse than a slow query.

  readinessProbe -> /ready  -> failing REMOVES the pod from the Service endpoints.
                    Therefore it SHOULD check dependencies: a pod that cannot reach the
                    database should stop receiving traffic but keep running, because it will
                    recover on its own the moment the database does.
"""

from fastapi import APIRouter, Request, Response, status

from app.db import database_reachable
from app.dependencies import CacheDep
from app.observability import READY_GAUGE, render_metrics
from app.schemas import ReadyBody

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
def health() -> dict[str, str]:
    """Liveness: the process is alive and the event loop is turning. No I/O, by design —
    see the module docstring. This handler must stay boring."""
    return {"status": "alive"}


@router.get(
    "/ready",
    response_model=ReadyBody,
    responses={
        503: {
            "model": ReadyBody,
            "description": "A dependency is unreachable; the body names it",
        }
    },
)
def ready(request: Request, response: Response, cache: CacheDep) -> ReadyBody:
    """Readiness: 200 only if Postgres and Redis are both reachable, else 503 naming the
    failed dependency, so `kubectl describe pod` tells you which one without a shell."""
    db_ok = database_reachable(request.app.state.engine)
    redis_ok = cache.ping()

    READY_GAUGE.labels(dependency="postgres").set(1 if db_ok else 0)
    READY_GAUGE.labels(dependency="redis").set(1 if redis_ok else 0)

    dependencies = {
        "postgres": "ok" if db_ok else "unreachable",
        "redis": "ok" if redis_ok else "unreachable",
    }

    if db_ok and redis_ok:
        return ReadyBody(status="ready", dependencies=dependencies)

    failed = "postgres" if not db_ok else "redis"
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyBody(status="not_ready", dependencies=dependencies, failed=failed)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus text format: request count, request latency, triage latency, fallbacks."""
    return Response(
        content=render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
