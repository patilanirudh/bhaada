from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, owner_id: int | None, action: str, entity: str, entity_id: int | None = None,
          details: dict | None = None) -> None:
    """Record an audit entry. Never put ID numbers or secrets in ``details``."""
    db.add(AuditLog(owner_id=owner_id, action=action, entity=entity, entity_id=entity_id, details=details))
