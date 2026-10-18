"""Bounded diagnostic events. Never accept arbitrary messages or patient payloads."""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .security import current_user
from .throttling import throttle

request_id = ContextVar("request_id", default="-")
logger = logging.getLogger("pulsemux.diagnostics")
router = APIRouter(prefix="/api")


class ClientDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "render_failure", "unhandled_error", "unhandled_rejection", "api_failure"
    ]
    status: int = Field(0, ge=0, le=599)
    request_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{32}$")


@router.post("/diagnostics", status_code=204)
def client_diagnostic(
    data: ClientDiagnostic, request: Request, user=Depends(current_user)
):
    throttle(request, namespace="diagnostics")
    logger.warning(
        "client_event kind=%s status=%s related_request_id=%s request_id=%s",
        data.kind,
        data.status,
        data.request_id or "-",
        request_id.get(),
    )
    return Response(status_code=204)


def install_observability(app):
    class RequestContextFilter(logging.Filter):
        def filter(self, record):
            record.request_id = request_id.get()
            return True

    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestContextFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s level=%(levelname)s logger=%(name)s request_id=%(request_id)s %(message)s"
            )
        )
    # These clients log full URLs at INFO, including sensitive query parameters.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True

    @app.middleware("http")
    async def correlate(request: Request, call_next):
        # Always generate locally: user-supplied IDs must not permit log injection.
        identifier = uuid.uuid4().hex
        token = request_id.set(identifier)
        started = time.monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = identifier
            if response.status_code >= 500:
                # No paths, query strings, headers, exception text, or request/response bodies.
                logger.error(
                    "server_failure status=%s request_id=%s duration_ms=%d",
                    response.status_code,
                    identifier,
                    int((time.monotonic() - started) * 1000),
                )
            return response
        except Exception as error:
            logger.error(
                "unhandled_server_failure request_id=%s error_type=%s",
                identifier,
                type(error).__name__,
            )
            # Uvicorn's exception logger otherwise includes potentially sensitive exception values.
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "detail": "The server could not complete the request.",
                    "request_id": identifier,
                },
                status_code=500,
                headers={
                    "X-Request-ID": identifier,
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "same-origin",
                },
            )
        finally:
            request_id.reset(token)
