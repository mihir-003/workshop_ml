"""No request body, medical symptom, login token, or personal data in audit events."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from clinic.database import Base, SessionLocal
from clinic.models import utcnow


class MCPAuditEvent(Base):
    __tablename__ = 'mcp_audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_role: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def record(role: str, actor_id: int, action: str, outcome: str) -> None:
    try:
        with SessionLocal.begin() as db:
            db.add(MCPAuditEvent(actor_role=role, actor_id=actor_id,
                                 action=action[:80], outcome=outcome[:20]))
    except Exception:
        # Audit failure must not allow an unauthorized action to succeed;
        # callers use this only after a terminal authorization decision.
        import logging
        logging.getLogger(__name__).exception('MCP audit write failed')
