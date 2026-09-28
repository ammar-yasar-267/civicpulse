"""Structured JSON logging to stdout (§2.2).

stdout, never a file: a container's filesystem is ephemeral and the log shipper reads the
stream. Writing to /var/log inside a pod produces logs that vanish with the pod and that
`kubectl logs` cannot see.

Every line carries request_id, propagated from X-Request-ID, so one citizen's submission is
greppable across the request, the triage attempt and the fallback warning.
"""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

# ContextVar rather than a thread local: it survives the async hop between the middleware
# that sets it and the sync service code that logs.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Stamps the ambient request_id onto every record, including records emitted by
    libraries that know nothing about our middleware."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    formatter = JsonFormatter(
        "{levelname}{name}{message}{asctime}",
        style="{",
        rename_fields={"levelname": "level", "asctime": "timestamp", "name": "logger"},
        timestamp=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn ships its own handlers; strip them so every line is JSON on one stream
    # rather than a mix of JSON and uvicorn's coloured text.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # The access log is replaced by our own middleware line, which carries request_id,
    # latency and the route template rather than a raw path.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str | None:
    return request_id_var.get()
