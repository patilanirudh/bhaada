"""Request dependencies: DB session, current owner and owner-scoped data access.

``OwnerScope`` is the single gateway routers use to read owner data. Every
query it builds is filtered by ``owner_id``, so owner A can never load owner
B's rows (tests in ``tests/test_isolation.py`` prove this).
"""
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Owner
from app.security import decode_token

DB = Annotated[Session, Depends(get_db)]

M = TypeVar("M")


def get_current_owner(request: Request, db: DB) -> Owner:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    data = decode_token(auth[7:], "access")
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    owner = db.get(Owner, int(data["sub"]))
    if not owner:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return owner


CurrentOwner = Annotated[Owner, Depends(get_current_owner)]


class OwnerScope:
    def __init__(self, db: Session, owner: Owner):
        self.db = db
        self.owner = owner
        self.owner_id = owner.id

    def select(self, model: type[M]) -> Select:
        return select(model).where(model.owner_id == self.owner_id)  # type: ignore[attr-defined]

    def all(self, model: type[M], *where, order_by=None) -> list[M]:
        stmt = self.select(model).where(*where)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        return list(self.db.scalars(stmt))

    def get(self, model: type[M], obj_id: int | None) -> M | None:
        if obj_id is None:
            return None
        return self.db.scalar(self.select(model).where(model.id == obj_id))  # type: ignore[attr-defined]

    def get_or_404(self, model: type[M], obj_id: int, label: str | None = None) -> M:
        obj = self.get(model, obj_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label or model.__name__} not found")
        return obj


def get_scope(db: DB, owner: CurrentOwner) -> OwnerScope:
    return OwnerScope(db, owner)


Scope = Annotated[OwnerScope, Depends(get_scope)]
