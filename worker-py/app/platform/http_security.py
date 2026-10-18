"""Deployment security policy for the same-origin dashboard."""

import os
from urllib.parse import urlsplit
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


def install_http_security(app):
    production = os.getenv("PLATFORM_ENV") == "production"
    public = urlsplit(os.getenv("PUBLIC_BASE_URL", ""))
    if production:
        if (
            public.scheme != "https"
            or not public.hostname
            or public.path not in ("", "/")
            or public.username
            or public.query
            or public.fragment
        ):
            raise RuntimeError("Production PUBLIC_BASE_URL must be an HTTPS origin")
        if not os.getenv("REDIS_URL"):
            raise RuntimeError(
                "Production REDIS_URL is required for shared login throttling"
            )
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[public.hostname, "localhost", "127.0.0.1"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if (
            production
            and request.url.path != "/readyz"
            and request.url.scheme != "https"
        ):
            return JSONResponse({"detail": "HTTPS is required"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = (
            "microphone=(self), camera=(), geolocation=()"
        )
        if (
            request.url.path.startswith("/dashboard/assets/")
            and response.status_code == 200
        ):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.url.path.startswith(("/api/", "/dashboard")):
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/dashboard"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                "media-src 'self' blob:; worker-src 'self' blob:; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
            )
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
