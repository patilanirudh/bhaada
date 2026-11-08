"""Public (no login) tenant self-registration. Anti-abuse (rate limit, honeypot) is an HTTP
concern and lives here; validation and storage live in ``app.services.registration``."""
import logging

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.deps import DB, client_ip
from app.core.config import get_settings
from app.core.errors import RateLimited
from app.services import registration as svc
from app.utils.ratelimit import limiter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/register/{token}")
def registration_info(token: str, db: DB):
    return svc.public_info(db, token)


async def _read(f: UploadFile | None, label: str) -> svc.Upload | None:
    if f is None or not f.filename:
        return None
    return svc.Upload(await f.read(svc.MAX_UPLOAD + 1), label)


@router.post("/register/{token}", status_code=201)
async def submit_registration(
    token: str,
    request: Request,
    db: DB,
    full_name: str = Form(..., min_length=2, max_length=150),
    phone: str = Form(..., max_length=20),
    email: str = Form(..., max_length=255),
    permanent_address: str = Form(..., min_length=5, max_length=1000),
    id_type: str = Form(..., max_length=10),
    id_number: str = Form(..., max_length=20),
    consent: bool = Form(False),
    rules_accepted: bool = Form(False),
    website: str = Form(""),  # honeypot: humans never fill this
    id_document: UploadFile = File(...),
    photo: UploadFile | None = File(None),
):
    if not limiter.allow(f"register:{client_ip(request)}", get_settings().registration_rate_limit, 3600):
        raise RateLimited("Too many submissions. Please try again later.")
    svc.get_usable_link(db, token)  # fail fast on bad links before reading uploads
    if website.strip():
        log.info("Honeypot triggered on a registration link")
        return {"detail": "Registration submitted"}  # look like success to bots, store nothing
    form = svc.RegistrationForm(
        full_name=full_name, phone=phone, email=email, permanent_address=permanent_address, id_type=id_type,
        id_number=id_number, consent=consent, rules_accepted=rules_accepted,
        id_document=await _read(id_document, "ID document") or svc.Upload(b"", "ID document"),
        photo=await _read(photo, "Photo"),
    )
    svc.submit_registration(db, token, form)
    return {"detail": "Registration submitted. The owner will review and confirm."}
