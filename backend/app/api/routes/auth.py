from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.defaults import DEFAULT_HOUSE_RULES
from app.api.deps import DB, CurrentOwner
from app.db.models import Owner
from app.schemas import (
    ChangePasswordIn,
    ForgotIn,
    LoginIn,
    OwnerOut,
    RegisterIn,
    ResetIn,
    TokenOut,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_token,
    hash_password,
    password_fingerprint,
    verify_password,
)
from app.services.audit import audit
from app.integrations.email import EmailError, send_email, system_credentials
from app.utils.ratelimit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "refresh_token"


def owner_out(owner: Owner) -> OwnerOut:
    out = OwnerOut.model_validate(owner)
    out.gmail_configured = bool(owner.gmail_address and owner.gmail_app_password_encrypted)
    out.default_house_rules = owner.default_house_rules or DEFAULT_HOUSE_RULES
    return out


def _set_refresh(response: Response, owner: Owner) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(owner.id, owner.token_version),
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        path="/api/auth",
    )


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, response: Response, db: DB):
    email = body.email.lower()
    if db.scalar(select(Owner).where(func.lower(Owner.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    owner = Owner(name=body.name.strip(), email=email, password_hash=hash_password(body.password), phone=body.phone)
    db.add(owner)
    db.flush()
    audit(db, owner.id, "create", "owner", owner.id)
    db.commit()
    _set_refresh(response, owner)
    return TokenOut(access_token=create_access_token(owner.id))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    if not limiter.allow(f"login:{_client_ip(request)}", 20, 900):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts. Try again later.")
    owner = db.scalar(select(Owner).where(func.lower(Owner.email) == body.email.lower()))
    if not owner or not verify_password(body.password, owner.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    _set_refresh(response, owner)
    return TokenOut(access_token=create_access_token(owner.id))


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: DB):
    token = request.cookies.get(REFRESH_COOKIE)
    data = decode_token(token, "refresh") if token else None
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    owner = db.get(Owner, int(data["sub"]))
    if not owner or owner.token_version != data.get("tv"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended, please log in again")
    _set_refresh(response, owner)  # rotate
    return TokenOut(access_token=create_access_token(owner.id))


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(REFRESH_COOKIE)
    data = decode_token(token, "refresh") if token else None
    if data:
        owner = db.get(Owner, int(data["sub"]))
        if owner and owner.token_version == data.get("tv"):
            owner.token_version += 1  # revoke all refresh tokens
            db.commit()
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth", secure=s.cookie_secure, samesite=s.cookie_samesite)
    response.status_code = 204
    return response


@router.get("/me", response_model=OwnerOut)
def me(owner: CurrentOwner):
    return owner_out(owner)


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, request: Request, db: DB):
    generic = {"detail": "If that email is registered, a reset link has been sent."}
    if not limiter.allow(f"forgot:{_client_ip(request)}", 5, 3600):
        return generic
    owner = db.scalar(select(Owner).where(func.lower(Owner.email) == body.email.lower()))
    if owner:
        token = create_reset_token(owner.id, owner.password_hash)
        link = f"{get_settings().frontend_url.rstrip('/')}/reset-password?token={token}"
        text = (
            f"Hi {owner.name},\n\nSomeone asked to reset your Rent Manager password.\n"
            f"Open this link within 1 hour to choose a new password:\n{link}\n\n"
            "If you did not ask for this, ignore this email."
        )
        try:
            send_email(system_credentials(), owner.email, "Reset your Rent Manager password", text)
        except EmailError:
            pass
    return generic


@router.post("/reset-password")
def reset_password(body: ResetIn, db: DB):
    data = decode_token(body.token, "reset")
    owner = db.get(Owner, int(data["sub"])) if data else None
    if not owner or data.get("pwf") != password_fingerprint(owner.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has already been used")
    owner.password_hash = hash_password(body.password)
    owner.token_version += 1
    audit(db, owner.id, "update", "owner", owner.id, {"field": "password_reset"})
    db.commit()
    return {"detail": "Password updated. You can log in now."}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, response: Response, owner: CurrentOwner, db: DB):
    if not verify_password(body.current_password, owner.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    owner.password_hash = hash_password(body.new_password)
    owner.token_version += 1
    audit(db, owner.id, "update", "owner", owner.id, {"field": "password"})
    db.commit()
    _set_refresh(response, owner)
    return {"detail": "Password changed"}
