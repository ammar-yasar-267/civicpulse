"""Application assembly.

Holds startup/shutdown, middleware and the exception handlers that turn domain errors into
the documented response bodies. No business rules, no SQL.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db import build_engine, build_session_factory
from app.logging_setup import configure_logging, set_request_id
from app.observability import REQUEST_COUNT, REQUEST_LATENCY
from app.providers.cache import CacheProvider, build_redis_client
from app.providers.ratelimit import RateLimiter
from app.providers.triage.factory import build_provider
from app.routes import complaints, health, meta, stats
from app.schemas import ErrorBody, FieldError
from app.services.triage_service import TriageService

logger = logging.getLogger(__name__)

API_TITLE = "CivicPulse API"
API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build long-lived resources once, tear them down on SIGTERM.

    Graceful shutdown (§2.2): uvicorn stops accepting new connections on SIGTERM and waits
    for in-flight requests to finish; this block then runs, closing the pool and the Redis
    client. Without it every rolling update drops live requests — and the preStop sleep in
    the Deployment gives the Service time to remove the pod before any of this starts.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = build_engine(settings)
    redis_client = build_redis_client(settings.redis_url)
    cache = CacheProvider(redis_client)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.cache = cache
    app.state.rate_limiter = RateLimiter(
        redis_client,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    app.state.triage_service = TriageService(
        provider=build_provider(settings),
        cache=cache,
        settings=settings,
    )

    logger.info(
        "application started",
        extra={
            "triage_provider": app.state.triage_service.active_provider,
            "stats_cache_ttl_seconds": settings.stats_cache_ttl_seconds,
            "rate_limit": f"{settings.rate_limit_requests}/{settings.rate_limit_window_seconds}s",
        },
    )

    try:
        yield
    finally:
        # Ordered deliberately: connections first, then the log line, so a failure closing
        # the pool is still reported.
        logger.info("shutting down: draining connections")
        engine.dispose()
        try:
            redis_client.close()
        except Exception as exc:  # never fail a shutdown over a cache client
            logger.warning("redis client close failed", extra={"error": str(exc)})
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=(
            "Municipal complaint intake, triage and operations API. "
            "The OpenAPI schema published here is what the frontend's typed client is "
            "generated from — see frontend/src/api."
        ),
        lifespan=lifespan,
    )

    # The frontend is served from a different origin in dev (Vite on 5173) and proxied
    # through nginx in prod. Origins come from the environment; no wildcard, because
    # allow_credentials with "*" is rejected by browsers and by good sense.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Cache",
            "X-Request-ID",
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        """Propagate X-Request-ID, time the request, record metrics, log one line.

        The id is generated when absent so every request is traceable even if the caller
        did not bother, and it is echoed back so a citizen reporting a problem can quote it.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started
            route = _route_template(request)
            REQUEST_COUNT.labels(request.method, route, "5xx").inc()
            REQUEST_LATENCY.labels(request.method, route).observe(duration)
            logger.exception(
                "unhandled exception",
                extra={"route": route, "method": request.method, "request_id": request_id},
            )
            raise

        duration = time.perf_counter() - started
        route = _route_template(request)

        REQUEST_COUNT.labels(request.method, route, f"{response.status_code // 100}xx").inc()
        REQUEST_LATENCY.labels(request.method, route).observe(duration)

        response.headers["X-Request-ID"] = request_id

        # Probes fire every couple of seconds; logging them would bury the real traffic.
        if request.url.path not in ("/health", "/ready", "/metrics"):
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "route": route,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                    "request_id": request_id,
                },
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """400 with a field-level body (§2.2), not FastAPI's default 422.

        The contract says 400 and says field-level, because the submit form needs to know
        *which* input to highlight.
        """
        fields = [
            FieldError(
                field=".".join(str(p) for p in err["loc"] if p not in ("body", "query")) or "body",
                message=err["msg"],
            )
            for err in exc.errors()
        ]
        body = ErrorBody(
            error="validation_error",
            detail="The submitted complaint failed validation.",
            fields=fields,
        )
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Normalise every error onto ErrorBody so clients parse one shape.

        Routes raise HTTPException with a dict detail already in that shape; anything else
        (a bare 404 from Starlette, say) gets wrapped here.
        """
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = ErrorBody(
                error=f"http_{exc.status_code}",
                detail=str(detail),
            ).model_dump()
        return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

    app.include_router(health.router)
    app.include_router(complaints.router)
    app.include_router(stats.router)
    app.include_router(meta.router)

    return app


def _route_template(request: Request) -> str:
    """The route *pattern* (/api/complaints/{complaint_id}), never the raw path.

    A UUID in a Prometheus label is unbounded cardinality: it grows a new time series per
    complaint and eventually takes out the metrics backend.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


app = create_app()
