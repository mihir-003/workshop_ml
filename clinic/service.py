from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from clinic.models import Appointment, Doctor, Slot, Treatment, utcnow


def history(db: Session, user_id: int):
    treatments = db.scalars(select(Treatment).where(Treatment.user_id == user_id).order_by(Treatment.updated_at.desc()).limit(5)).all()
    appointments = db.scalars(select(Appointment).where(Appointment.user_id == user_id, Appointment.status == "booked").order_by(Appointment.created_at.desc()).limit(5)).all()
    return {"treatments": [{"condition": t.condition, "summary": t.summary, "ongoing": t.ongoing, "doctor": t.doctor.name, "doctor_id": t.doctor_id} for t in treatments],
            "appointments": [{"id": a.id, "doctor": a.doctor.name, "specialty": a.doctor.specialty, "starts_at": a.slot.starts_at.isoformat() + "Z", "reason": a.reason} for a in appointments]}


def available(db: Session, specialty: str | None = None, doctor_id: int | None = None):
    query = (select(Slot).join(Doctor).where(Slot.booked.is_(False), Slot.starts_at > utcnow(), Slot.starts_at < utcnow() + timedelta(days=30), Doctor.active.is_(True)).order_by(Slot.starts_at).limit(30))
    if specialty:
        query = query.where(Doctor.specialty == specialty)
    if doctor_id:
        query = query.where(Doctor.id == doctor_id)
    return [{"slot_id": s.id, "doctor_id": s.doctor_id, "doctor": s.doctor.name, "specialty": s.doctor.specialty, "starts_at": s.starts_at.isoformat() + "Z", "ends_at": s.ends_at.isoformat() + "Z"} for s in db.scalars(query)]


def book(db: Session, user_id: int, slot_id: int, reason: str):
    # Conditional UPDATE is atomic on MySQL and prevents double booking across workers.
    result = db.execute(update(Slot).where(Slot.id == slot_id, Slot.booked.is_(False), Slot.starts_at > utcnow(), Slot.doctor_id.in_(select(Doctor.id).where(Doctor.active.is_(True)))).values(booked=True))
    if result.rowcount != 1:
        db.rollback()
        return None
    slot = db.get(Slot, slot_id)
    appointment = Appointment(user_id=user_id, doctor_id=slot.doctor_id, slot_id=slot_id, reason=reason[:500], status="booked")
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


def cancel(db: Session, user_id: int, appointment_id: int):
    appointment = db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.user_id == user_id, Appointment.status == "booked"))
    if not appointment or appointment.slot.starts_at <= utcnow():
        return False
    appointment.status = "cancelled"
    appointment.slot.booked = False
    db.commit()
    return True
