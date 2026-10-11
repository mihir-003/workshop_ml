"""Whitelisted, ORM-only operations. Neither callers nor the LLM can submit SQL."""
from datetime import datetime

from sqlalchemy import func, or_, select, text

from clinic.database import SessionLocal, engine
from clinic.models import Appointment, Doctor, Slot, User, utcnow
from clinic.slot_service import expire_slots, validate_slot
from care_assistant.repository import (appointment_dict, available_slots, book_slot,
                                       cancel_booking)
from mcp_rbac.auth import AccessDenied, Principal


def missing():
    return {'status': 'NO', 'reply': 'NO', 'data': None}


def found(data, reply='Verified database result.'):
    return {'status': 'OK', 'reply': reply, 'data': data}


def _positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not 0 < int(value) < 2_147_483_647:
        raise ValueError(f'{field} must be a positive integer.')
    return int(value)


def _admin_still_valid(principal: Principal) -> None:
    """Refresh the admin role and is_active bit, even on direct MCP invocation."""
    if principal.role not in {'admin', 'super_admin'}:
        return
    from clinic.admin_db import init_admin_tables
    init_admin_tables()
    with engine.connect() as conn:
        row = conn.execute(text('SELECT role, is_active FROM admin_users WHERE id=:id'),
                           {'id': principal.subject_id}).mappings().first()
    if not row or not row['is_active'] or row['role'] != principal.role:
        raise AccessDenied('Admin access was revoked or changed.')


def profile(principal: Principal):
    with SessionLocal() as db:
        u = db.get(User, principal.subject_id)
        return found({'id': u.id, 'name': u.name, 'email': u.email}) if u else missing()


def slots(principal: Principal, specialty: str = '', doctor_name: str = '', limit: int = 10):
    limit = max(1, min(int(limit), 30))
    specialty = specialty.strip()[:50] or None
    doctor_name = doctor_name.strip()[:100]
    with SessionLocal() as db:
        if doctor_name:
            query = select(Doctor.id).where(Doctor.active.is_(True),
                Doctor.name.ilike(f'%{doctor_name}%'))
            if specialty:
                query = query.where(Doctor.specialty == specialty)
            doctor_ids = list(db.scalars(query.order_by(Doctor.id).limit(30)))
            items = []
            for doctor_id in doctor_ids:
                items.extend(available_slots(db, doctor_id=doctor_id, limit=limit))
                if len(items) >= limit:
                    break
            items.sort(key=lambda item: item['starts_at'])
        else:
            items = available_slots(db, specialty=specialty, limit=limit)
        return found(items[:limit], f'{min(len(items), limit)} verified available slot(s).') if items else missing()


def book(principal: Principal, slot_id: int, reason: str = 'Consultation'):
    slot_id = _positive(slot_id, 'slot_id')
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValueError('Reason must not exceed 500 characters.')
    with SessionLocal() as db:
        if not db.get(User, principal.subject_id):
            return missing()
        appointment = book_slot(db, principal.subject_id, slot_id, reason)
        return found(appointment_dict(appointment), 'Booking confirmed.') if appointment else missing()


def appointments(principal: Principal):
    with SessionLocal() as db:
        if not db.get(User, principal.subject_id):
            return missing()
        rows = db.scalars(select(Appointment).where(Appointment.user_id == principal.subject_id)
                          .order_by(Appointment.id.desc()).limit(30)).all()
        return found([appointment_dict(row) for row in rows]) if rows else missing()


def cancel(principal: Principal, appointment_id: int):
    appointment_id = _positive(appointment_id, 'appointment_id')
    with SessionLocal() as db:
        item = cancel_booking(db, principal.subject_id, appointment_id)
        return found(item, 'Appointment cancelled.') if item else missing()


def admin_doctors(principal: Principal, search: str = ''):
    _admin_still_valid(principal)
    with SessionLocal() as db:
        q = select(Doctor).order_by(Doctor.name).limit(50)
        search = search.strip()[:100]
        if search:
            q = select(Doctor).where(or_(Doctor.name.ilike(f'%{search}%'),
                                           Doctor.specialty.ilike(f'%{search}%'))).order_by(Doctor.name).limit(50)
        rows = [{'id': d.id, 'name': d.name, 'specialty': d.specialty, 'active': d.active}
                for d in db.scalars(q)]
        return found(rows) if rows else missing()


def admin_add_slot(principal: Principal, doctor_id: int, starts_at: str, minutes: int = 30):
    _admin_still_valid(principal)
    doctor_id = _positive(doctor_id, 'doctor_id')
    minutes = int(minutes)
    try:
        start = datetime.fromisoformat(starts_at)
    except (TypeError, ValueError) as exc:
        raise ValueError('starts_at must be ISO datetime, e.g. 2026-12-01T10:00:00+05:30.') from exc
    with SessionLocal() as db:
        start, end = validate_slot(db, doctor_id, start, minutes)
        slot = Slot(doctor_id=doctor_id, starts_at=start, ends_at=end, booked=False)
        db.add(slot)
        db.commit()
        return found({'slot_id': slot.id, 'doctor_id': doctor_id,
                      'starts_at': start.isoformat() + 'Z'}, 'Slot created.')


def admin_appointments(principal: Principal, limit: int = 20):
    _admin_still_valid(principal)
    with SessionLocal() as db:
        limit = max(1, min(int(limit), 50))
        rows = db.scalars(select(Appointment).order_by(Appointment.id.desc()).limit(limit)).all()
        return found([{'appointment': appointment_dict(a), 'user_id': a.user_id}
                      for a in rows]) if rows else missing()


def admin_set_status(principal: Principal, appointment_id: int, status: str):
    _admin_still_valid(principal)
    from clinic.admin_repository import SchemaError, update_booking_status
    appointment_id = _positive(appointment_id, 'appointment_id')
    status = status.strip().lower()
    if status not in {'booked', 'confirmed', 'pending', 'cancelled', 'completed'}:
        raise ValueError('Invalid appointment status.')
    try:
        update_booking_status(appointment_id, status)
    except SchemaError as exc:
        if str(exc) == 'Appointment not found.':
            return missing()
        raise ValueError(str(exc)) from exc
    return found({'appointment_id': appointment_id, 'status': status}, 'Appointment status updated.')


def admin_stats(principal: Principal):
    _admin_still_valid(principal)
    with SessionLocal() as db:
        return found({'users': db.scalar(select(func.count()).select_from(User)),
                      'doctors': db.scalar(select(func.count()).select_from(Doctor)),
                      'appointments': db.scalar(select(func.count()).select_from(Appointment)),
                      'free_future_slots': db.scalar(select(func.count()).select_from(Slot)
                          .where(Slot.starts_at > utcnow(), Slot.booked.is_(False)))})


def admin_audit(principal: Principal, limit: int = 20):
    _admin_still_valid(principal)
    from mcp_rbac.audit import MCPAuditEvent
    with SessionLocal() as db:
        limit = max(1, min(int(limit), 50))
        rows = db.scalars(select(MCPAuditEvent).order_by(MCPAuditEvent.id.desc()).limit(limit)).all()
        return found([{'id': r.id, 'role': r.actor_role, 'actor_id': r.actor_id,
                       'action': r.action, 'outcome': r.outcome,
                       'created_at': r.created_at.isoformat()} for r in rows]) if rows else missing()


def admin_set_role(principal: Principal, admin_id: int, role: str):
    _admin_still_valid(principal)
    if principal.role != 'super_admin':
        raise AccessDenied('Super Admin permission required.')
    admin_id = _positive(admin_id, 'admin_id')
    if role not in {'admin', 'super_admin'}:
        raise ValueError('Only admin or super_admin are assignable to admin accounts.')
    with engine.begin() as conn:
        row = conn.execute(text('SELECT id, role FROM admin_users WHERE id=:id'),
                           {'id': admin_id}).mappings().first()
        if not row:
            return missing()
        if admin_id == principal.subject_id and role != 'super_admin':
            raise ValueError('Cannot remove your own Super Admin role.')
        conn.execute(text('UPDATE admin_users SET role=:role WHERE id=:id'),
                     {'role': role, 'id': admin_id})
    return found({'admin_id': admin_id, 'role': role}, 'Admin role changed.')


def system_integrity(principal: Principal):
    with SessionLocal() as db:
        rows = db.scalars(select(Appointment).limit(1000)).all()
        problems = [a.id for a in rows if a.status in {'booked', 'confirmed', 'pending'} and not a.slot.booked]
        return found({'checked': len(rows), 'inconsistent_appointment_ids': problems,
                      'sample_capped': len(rows) == 1000})


def system_cleanup(principal: Principal):
    with SessionLocal() as db:
        count = expire_slots(db)
        return found({'expired_slots_removed': count}, 'Maintenance completed.')
