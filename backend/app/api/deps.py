"""FastAPI dependencies: DB session, authenticated owner and owner-scoped data access."""
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import Unauthorized
from app.core.security import decode_token
from app.db.models import Owner
from app.db.scope import OwnerScope
from app.db.session import get_db

DB = Annotated[Session, Depends(get_db)]


def get_current_owner(request: Request, db: DB) -> Owner:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Not authenticated")
    data = decode_token(auth[7:], "access")
    if not data:
        raise Unauthorized("Session expired, please log in again")
    owner = db.get(Owner, int(data["sub"]))
    if not owner:
        raise Unauthorized("Account not found")
    return owner


CurrentOwner = Annotated[Owner, Depends(get_current_owner)]


def get_scope(db: DB, owner: CurrentOwner) -> OwnerScope:
    return OwnerScope(db, owner)


Scope = Annotated[OwnerScope, Depends(get_scope)]


def client_ip(request: Request) -> str:
    """Client IP. Behind Vercel/Render the first X-Forwarded-For hop is the client."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
