import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.routers import (
    auth,
    dashboard,
    excel,
    jobs,
    links,
    properties,
    public,
    reminders,
    rent,
    settings,
    tenants,
)
from app.security import decode_token
from app.services.storage import LocalStorage, get_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

s = get_settings()


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
    allow_headers=["Authorization", "Content-Type", "X-Cron-Secret"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if not request.url.path.startswith("/api/files/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if s.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Return readable field errors: {"detail": "...", "errors": {"field": "message"}}."""
    errors: dict[str, str] = {}
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path", "form")]
        field = ".".join(loc) or "request"
        msg = e.get("msg", "Invalid value").removeprefix("Value error, ")
        errors.setdefault(field, msg)
    first = next(iter(errors.items()), ("request", "Invalid input"))
    return JSONResponse(status_code=422, content={"detail": f"{first[0]}: {first[1]}", "errors": errors})


for r in (auth, settings, properties, links, public, tenants, rent, excel, reminders, dashboard, jobs):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/files/signed")
def signed_file(token: str):
    """Serves local-storage files behind short-lived signed tokens (dev / local backend only)."""
    data = decode_token(token, "file")
    if not data:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Link expired")
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    content = storage.read(data["path"])
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    from app.utils.validators import sniff_mime

    path = data["path"]
    mime = sniff_mime(content) or (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if path.endswith(".xlsx")
        else "application/octet-stream"
    )
    filename = path.rsplit("/", 1)[-1]
    return Response(content, media_type=mime, headers={
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, max-age=60",
    })
