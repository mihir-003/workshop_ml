from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clinic.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    user: Mapped[User] = relationship()


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    specialty: Mapped[str] = mapped_column(String(50), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("doctor_id", "starts_at", name="uq_doctor_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, naive in DB
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    booked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    doctor: Mapped[Doctor] = relationship()


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointment_user_status", "user_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500), default="Consultation")
    status: Mapped[str] = mapped_column(String(20), default="booked")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    doctor: Mapped[Doctor] = relationship()
    slot: Mapped[Slot] = relationship()


class Treatment(Base):
    __tablename__ = "treatments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    condition: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    ongoing: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    doctor: Mapped[Doctor] = relationship()


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
