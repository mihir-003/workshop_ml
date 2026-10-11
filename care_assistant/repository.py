"""Patient-scoped records and transactional booking/cancellation operations."""
from datetime import datetime
from sqlalchemy import ForeignKey, JSON, select, update, inspect, text
from sqlalchemy.orm import Mapped, mapped_column
from clinic.database import Base
from clinic.models import Appointment, ChatMessage, Doctor, LoginSession, Slot, Treatment, utcnow
from clinic.slot_service import expire_slots, future_slots

ACTIVE_BOOKINGS = ('booked', 'confirmed', 'pending')


class ChatState(Base):
    __tablename__ = 'assistant_chat_state'
    session_id: Mapped[int] = mapped_column(ForeignKey('login_sessions.id', ondelete='CASCADE'), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


def get_state(db, session_id):
    row = db.get(ChatState, session_id)
    return dict(row.data) if row else {}


def save_state(db, session_id, state):
    row = db.get(ChatState, session_id)
    if row:
        row.data = dict(state)
    else:
        db.add(ChatState(session_id=session_id, data=dict(state)))
    db.flush()


def active_specialties(db):
    return list(db.scalars(select(Doctor.specialty).where(Doctor.active.is_(True)).distinct().order_by(Doctor.specialty)))


def all_specialties(db):
    return list(db.scalars(select(Doctor.specialty).distinct().order_by(Doctor.specialty)))


def has_active_doctor(db, specialty):
    return bool(db.scalar(select(Doctor.id).where(Doctor.active.is_(True), Doctor.specialty == specialty).limit(1)))


def slot_dict(row):
    return {'slot_id': row.id, 'doctor_id': row.doctor_id, 'doctor': row.doctor.name,
            'specialty': row.doctor.specialty, 'starts_at': row.starts_at.isoformat()+'Z',
            'ends_at': row.ends_at.isoformat()+'Z'}


def available_slots(db, specialty=None, doctor_id=None, limit=30, after=None, before=None):
    return [slot_dict(row) for row in future_slots(db, specialty, doctor_id, after, before, limit)]


def appointment_dict(a):
    return {'id': a.id, 'doctor_id': a.doctor_id, 'doctor': a.doctor.name, 'specialty': a.doctor.specialty,
            'slot_id': a.slot_id, 'starts_at': a.slot.starts_at.isoformat()+'Z', 'reason': a.reason, 'status': a.status}


def upcoming_bookings(db, user_id):
    query = select(Appointment).join(Slot).where(Appointment.user_id == user_id,
        Appointment.status.in_(ACTIVE_BOOKINGS), Slot.starts_at > utcnow()).order_by(Slot.starts_at, Appointment.id)
    return [appointment_dict(a) for a in db.scalars(query)]


def patient_history(db, user_id):
    treatments = db.scalars(select(Treatment).where(Treatment.user_id == user_id).order_by(Treatment.ongoing.desc(), Treatment.updated_at.desc()).limit(5)).all()
    return {'treatments': [{'id': t.id, 'condition': t.condition, 'summary': t.summary, 'ongoing': t.ongoing,
        'doctor_id': t.doctor_id, 'doctor': t.doctor.name, 'specialty': t.doctor.specialty} for t in treatments],
        'appointments': upcoming_bookings(db, user_id)}


def recent_chat(db, user_id, limit=12):
    rows = db.scalars(select(ChatMessage).where(ChatMessage.user_id == user_id).order_by(ChatMessage.id.desc()).limit(limit)).all()
    return [{'role': m.role, 'content': m.content[:2000]} for m in reversed(rows) if m.role in {'user', 'assistant'}]


def remember_chat(db, user_id, user_text, assistant_text, specialty=None):
    db.add_all([ChatMessage(user_id=user_id, role='user', content=user_text[:2000], specialty=specialty),
                ChatMessage(user_id=user_id, role='assistant', content=assistant_text[:4000])])
    db.commit()


def sync_admin_status(db, appointment_id, status):
    # Some existing admin versions overlay the core status with this auxiliary table.
    if inspect(db.connection()).has_table('admin_booking_status'):
        found = db.execute(text('SELECT id FROM admin_booking_status WHERE booking_id=:id'), {'id': appointment_id}).first()
        if found:
            db.execute(text('UPDATE admin_booking_status SET status=:status WHERE booking_id=:id'), {'id': appointment_id, 'status': status})
        else:
            db.execute(text('INSERT INTO admin_booking_status (booking_id,status) VALUES (:id,:status)'), {'id': appointment_id, 'status': status})


def book_slot(db, user_id, slot_id, reason):
    expire_slots(db)
    result = db.execute(update(Slot).where(Slot.id == slot_id, Slot.booked.is_(False), Slot.starts_at > utcnow(),
        Slot.doctor_id.in_(select(Doctor.id).where(Doctor.active.is_(True)))).values(booked=True))
    if result.rowcount != 1:
        db.rollback()
        return None
    slot = db.get(Slot, slot_id)
    a = Appointment(user_id=user_id, doctor_id=slot.doctor_id, slot_id=slot.id, reason=(reason.strip() or 'Consultation')[:500], status='booked')
    db.add(a); db.flush()
    sync_admin_status(db, a.id, 'booked')
    db.commit(); db.refresh(a)
    return a


def cancel_booking(db, user_id, appointment_id):
    # Lock slot first; the same ordering is used by admin status changes and booking.
    identity = db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.user_id == user_id))
    if not identity:
        return None
    slot = db.scalar(select(Slot).where(Slot.id == identity.slot_id).with_for_update())
    a = db.scalar(select(Appointment).where(Appointment.id == appointment_id,
        Appointment.user_id == user_id).with_for_update().execution_options(populate_existing=True))
    if not slot or not a or a.status not in ACTIVE_BOOKINGS or slot.starts_at <= utcnow():
        db.rollback()
        return None
    result = appointment_dict(a)
    a.status = 'cancelled'
    slot.booked = False
    sync_admin_status(db, a.id, 'cancelled')
    db.commit()
    result['status'] = 'cancelled'
    return result


# Stable helpers retained for compatibility with the previously installed clinic tools.
def last_specialty(db, user_id):
    return db.scalar(select(ChatMessage.specialty).where(ChatMessage.user_id == user_id,
        ChatMessage.role == 'user', ChatMessage.specialty.is_not(None)).order_by(ChatMessage.id.desc()).limit(1))


def doctor_options(db, specialty):
    result = []
    for doctor in db.scalars(select(Doctor).where(Doctor.active.is_(True), Doctor.specialty == specialty)):
        slots = available_slots(db, doctor_id=doctor.id, limit=5)
        if slots:
            result.append({'doctor_id': doctor.id, 'doctor': doctor.name, 'specialty': specialty, 'slots': slots})
    return result
