from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import Scope
from app.models import MessageTemplate
from app.routers.auth import owner_out
from app.schemas import GmailIn, OwnerOut, OwnerUpdate, TemplateIn, TemplateOut
from app.security import encrypt
from app.services.audit import audit
from app.services.email import EmailError, send_owner_email
from app.services.templates import DEFAULTS, KINDS, PLACEHOLDERS

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.put("/profile", response_model=OwnerOut)
def update_profile(body: OwnerUpdate, scope: Scope):
    owner = scope.owner
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(owner, k, v or None if k in ("phone", "upi_id") else v)
    audit(scope.db, owner.id, "update", "owner", owner.id, {"fields": list(data)})
    scope.db.commit()
    return owner_out(owner)


@router.put("/gmail", response_model=OwnerOut)
def set_gmail(body: GmailIn, scope: Scope):
    owner = scope.owner
    owner.gmail_address = body.gmail_address.lower()
    owner.gmail_app_password_encrypted = encrypt(body.app_password)
    audit(scope.db, owner.id, "update", "owner", owner.id, {"field": "gmail"})
    scope.db.commit()
    return owner_out(owner)


@router.delete("/gmail", response_model=OwnerOut)
def remove_gmail(scope: Scope):
    owner = scope.owner
    owner.gmail_address = None
    owner.gmail_app_password_encrypted = None
    audit(scope.db, owner.id, "update", "owner", owner.id, {"field": "gmail_removed"})
    scope.db.commit()
    return owner_out(owner)


@router.post("/gmail/test")
def test_gmail(scope: Scope):
    owner = scope.owner
    if not owner.gmail_address:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Save your Gmail address and App Password first")
    try:
        send_owner_email(owner, owner.email, "Rent Manager test email",
                         f"Hi {owner.name},\n\nYour Gmail is connected. Rent reminders will be sent from "
                         f"{owner.gmail_address}.")
    except EmailError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"detail": f"Test email sent to {owner.email}"}


@router.get("/templates")
def list_templates(scope: Scope):
    customs = {
        (t.kind, t.language): t.body
        for t in scope.all(MessageTemplate)
    }
    items = []
    for kind in KINDS:
        for lang in ("en", "hi"):
            body = customs.get((kind, lang))
            items.append(TemplateOut(kind=kind, language=lang, body=body or DEFAULTS[kind][lang],
                                     is_custom=body is not None))
    return {"kinds": KINDS, "placeholders": PLACEHOLDERS, "templates": items}


@router.put("/templates", response_model=TemplateOut)
def save_template(body: TemplateIn, scope: Scope):
    if body.kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown template")
    t = scope.db.scalar(select(MessageTemplate).where(
        MessageTemplate.owner_id == scope.owner_id, MessageTemplate.kind == body.kind,
        MessageTemplate.language == body.language))
    if t:
        t.body = body.body
    else:
        scope.db.add(MessageTemplate(owner_id=scope.owner_id, kind=body.kind, language=body.language, body=body.body))
    audit(scope.db, scope.owner_id, "update", "template", None, {"kind": body.kind, "language": body.language})
    scope.db.commit()
    return TemplateOut(kind=body.kind, language=body.language, body=body.body, is_custom=True)


@router.delete("/templates/{kind}/{language}", response_model=TemplateOut)
def reset_template(kind: str, language: str, scope: Scope):
    if kind not in KINDS or language not in ("en", "hi"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown template")
    t = scope.db.scalar(select(MessageTemplate).where(
        MessageTemplate.owner_id == scope.owner_id, MessageTemplate.kind == kind,
        MessageTemplate.language == language))
    if t:
        scope.db.delete(t)
        scope.db.commit()
    return TemplateOut(kind=kind, language=language, body=DEFAULTS[kind][language], is_custom=False)
