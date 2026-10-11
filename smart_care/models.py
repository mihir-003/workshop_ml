from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from clinic.database import Base
from clinic.models import utcnow
from datetime import datetime


class Episode(Base):
    __tablename__ = 'care_episodes'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    pending: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk: Mapped[str] = mapped_column(String(20), default='incomplete')
    risk_reason: Mapped[str] = mapped_column(Text, default='Assessment incomplete')
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    routing_reason: Mapped[str] = mapped_column(Text, default='')
    brief: Mapped[str] = mapped_column(Text, default='')
    brief_source: Mapped[str] = mapped_column(String(40), default='Structured facts')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Visit(Base):
    __tablename__ = 'care_visits'
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey('appointments.id'), unique=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey('care_episodes.id'), index=True)
    brief_snapshot: Mapped[str] = mapped_column(Text)
    treatment_id: Mapped[int | None] = mapped_column(ForeignKey('treatments.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Progress(Base):
    __tablename__ = 'care_progress'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    treatment_id: Mapped[int] = mapped_column(ForeignKey('treatments.id'), index=True)
    status: Mapped[str] = mapped_column(String(12))
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DoctorAccess(Base):
    __tablename__ = 'care_doctor_access'
    __table_args__ = (UniqueConstraint('user_id', name='uq_care_doctor_user'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    doctor_id: Mapped[int] = mapped_column(ForeignKey('doctors.id'), index=True)
