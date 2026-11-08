"""Application entry point: builds the FastAPI app, middleware, error handling and routes."""
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.routes import (
    auth,
    dashboard,
    excel,
    files,
    jobs,
    links,
    properties,
    public,
    reminders,
    rent,
    settings,
    tenants,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging

log = logging.getLogger("app")
access_log = logging.getLogger("app.access")

ROUTERS = (auth, settings, properties, links, public, tenants, rent, excel, reminders, dashboard, jobs, files)


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging()
    s.validate_for_production()  # refuse to boot with unsafe production settings

    app = FastAPI(
        title="Rent Manager API",
        version="1.0.0",
        docs_url=None if s.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if s.is_production else "/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Cron-Secret", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Request ID, access log (path only: query strings may carry signed tokens) and security headers."""
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        access_log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code, ms,
                        request_id)
        h = response.headers
        h["X-Request-ID"] = request_id
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.url.path.startswith("/api/files/"):
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            h.setdefault("Cache-Control", "no-store")
        if s.is_production:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        """Domain errors raised by services -> HTTP responses."""
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "errors": exc.errors})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        """Readable field errors: {"detail": "...", "errors": {"field": "message"}}."""
        errors: dict[str, str] = {}
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path", "form")]
            field = ".".join(loc) or "request"
            errors.setdefault(field, e.get("msg", "Invalid value").removeprefix("Value error, "))
        first = next(iter(errors.items()), ("request", "Invalid input"))
        return JSONResponse(status_code=422, content={"detail": f"{first[0]}: {first[1]}", "errors": errors})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        """Never leak internals: log with the request ID, return a generic message."""
        rid = getattr(request.state, "request_id", "-")
        log.exception("Unhandled error rid=%s path=%s", rid, request.url.path)
        return JSONResponse(status_code=500, content={
            "detail": f"Something went wrong. Please try again. (ref {rid})", "errors": {}})

    for r in ROUTERS:
        app.include_router(r.router)

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        return Response(status_code=204)

    return app


app = create_app()
