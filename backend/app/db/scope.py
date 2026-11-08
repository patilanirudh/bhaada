"""Owner-scoped data access.

``OwnerScope`` is the single gateway for reading owner data: every query it
builds is filtered by ``owner_id``, so one owner can never load another owner's
rows (proven by ``tests/test_isolation.py``).
"""
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db.models import Owner

M = TypeVar("M")


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
            raise NotFound(f"{label or model.__name__} not found")
        return obj
