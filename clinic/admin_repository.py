"""Admin operations on the same clinic models used by patient appointments."""
from datetime import datetime, timedelta

from sqlalchemy import MetaData, Table, func, inspect, or_, select
from clinic.database import SessionLocal
from clinic.models import Appointment, Doctor, Slot, Treatment, User, utcnow
from clinic.slot_service import expire_slots, to_ist, validate_slot
from care_assistant.repository import ACTIVE_BOOKINGS, sync_admin_status
from care_assistant.presentation import doctor_label


class SchemaError(ValueError):
    pass


def _profiles(db):
    if not inspect(db.connection()).has_table('admin_doctor_profiles'):
        raise SchemaError('Open the admin login page once to initialize doctor profiles.')
    return Table('admin_doctor_profiles', MetaData(), autoload_with=db.connection())


def _save_profile(db, doctor_id, profile):
    table = _profiles(db)
    values = {k: profile.get(k) or None for k in ('qualification', 'experience_years', 'phone', 'email', 'consultation_fee', 'about')}
    values['is_active'] = bool(profile.get('is_active', True))
    if db.scalar(select(table.c.id).where(table.c.doctor_id == doctor_id)):
        db.execute(table.update().where(table.c.doctor_id == doctor_id).values(**values))
    else:
        db.execute(table.insert().values(doctor_id=doctor_id, **values))


def dashboard_stats():
    with SessionLocal() as db:
        expire_slots(db)
        count = lambda model: db.scalar(select(func.count()).select_from(model))
        available = db.scalar(select(func.count()).select_from(Slot).join(Doctor).where(
            Slot.starts_at > utcnow(), Slot.booked.is_(False), Doctor.active.is_(True)))
        return {'doctors': count(Doctor), 'available_slots': available, 'bookings': count(Appointment), 'users': count(User)}


def list_doctors(search=''):
    with SessionLocal() as db:
        table = _profiles(db)
        profiles = {r['doctor_id']: dict(r) for r in db.execute(select(table)).mappings()}
        query = select(Doctor).order_by(Doctor.name)
        if search:
            query = query.where(or_(Doctor.name.ilike('%'+search+'%'), Doctor.specialty.ilike('%'+search+'%')))
        result = []
        for doctor in db.scalars(query):
            profile = profiles.get(doctor.id, {})
            profile['is_active'] = doctor.active
            result.append({'id': doctor.id, 'name': doctor_label(doctor.name), 'specialty': doctor.specialty, 'profile': profile})
        return result


def get_doctor(doctor_id):
    return next((doctor for doctor in list_doctors() if doctor['id'] == doctor_id), None)


def create_doctor(name, specialty, profile):
    if not name.strip() or not specialty.strip():
        raise SchemaError('Doctor name and specialty are required.')
    with SessionLocal.begin() as db:
        doctor = Doctor(name=name.strip(), specialty=specialty.strip(), active=bool(profile.get('is_active', True)))
        db.add(doctor); db.flush()
        _save_profile(db, doctor.id, profile)
        return doctor.id


def update_doctor(doctor_id, name, specialty, profile):
    if not name.strip() or not specialty.strip():
        raise SchemaError('Doctor name and specialty are required.')
    with SessionLocal.begin() as db:
        doctor = db.get(Doctor, doctor_id)
        if not doctor:
            raise SchemaError('Doctor not found.')
        doctor.name, doctor.specialty = name.strip(), specialty.strip()
        doctor.active = bool(profile.get('is_active', True))
        _save_profile(db, doctor_id, profile)


def delete_doctor(doctor_id):
    with SessionLocal.begin() as db:
        doctor = db.get(Doctor, doctor_id)
        if not doctor:
            raise SchemaError('Doctor not found.')
        # Retain foreign keys for appointments and treatment history.
        doctor.active = False
        table = _profiles(db)
        db.execute(table.update().where(table.c.doctor_id == doctor_id).values(is_active=False))


def list_slots(doctor_id=None):
    with SessionLocal() as db:
        expire_slots(db)
        query = select(Slot).join(Doctor).where(Slot.starts_at > utcnow())
        if doctor_id:
            query = query.where(Slot.doctor_id == doctor_id)
        result = []
        for slot in db.scalars(query.order_by(Slot.starts_at, Slot.id)):
            linked = bool(db.scalar(select(Appointment.id).where(Appointment.slot_id == slot.id).limit(1)))
            result.append({'id': slot.id, 'doctor_id': slot.doctor_id, 'doctor_name': doctor_label(slot.doctor.name),
                'start_time': to_ist(slot.starts_at), 'duration': int((slot.ends_at-slot.starts_at).total_seconds()/60),
                'is_booked': slot.booked, 'editable': not slot.booked and not linked,
                'expires_at': slot.starts_at.isoformat()+'Z'})
        return result


def create_slot(doctor_id, start_time, duration_minutes=30):
    with SessionLocal.begin() as db:
        start, end = validate_slot(db, doctor_id, start_time, duration_minutes)
        slot = Slot(doctor_id=doctor_id, starts_at=start, ends_at=end, booked=False)
        db.add(slot); db.flush()
        return slot.id


def bulk_create_slots(doctor_id, day, start_time, end_time, duration_minutes):
    if not 5 <= duration_minutes <= 240:
        raise SchemaError('Duration must be between 5 and 240 minutes.')
    current, finish = datetime.combine(day, start_time), datetime.combine(day, end_time)
    step = timedelta(minutes=duration_minutes)
    if finish <= current or current+step > finish:
        raise SchemaError('End time must allow at least one full slot after the start time.')
    count = 0
    with SessionLocal.begin() as db:
        while current+step <= finish:
            start, end = validate_slot(db, doctor_id, current, duration_minutes)
            db.add(Slot(doctor_id=doctor_id, starts_at=start, ends_at=end, booked=False))
            db.flush()
            current += step
            count += 1
    return count


def _editable_slot(db, slot_id):
    slot = db.scalar(select(Slot).where(Slot.id == slot_id).with_for_update())
    if not slot:
        raise SchemaError('Slot not found.')
    if slot.booked or db.scalar(select(Appointment.id).where(Appointment.slot_id == slot_id).limit(1)):
        raise SchemaError('Appointment-linked slots cannot be edited or deleted. Create a new time instead.')
    return slot


def update_slot(slot_id, doctor_id, start_time, duration_minutes):
    with SessionLocal.begin() as db:
        slot = _editable_slot(db, slot_id)
        start, end = validate_slot(db, doctor_id, start_time, duration_minutes, exclude=slot_id)
        slot.doctor_id, slot.starts_at, slot.ends_at = doctor_id, start, end


def delete_slot(slot_id):
    with SessionLocal.begin() as db:
        db.delete(_editable_slot(db, slot_id))


def list_users(search=''):
    with SessionLocal() as db:
        query = select(User).order_by(User.id.desc())
        if search:
            query = query.where(or_(User.name.ilike('%'+search+'%'), User.email.ilike('%'+search+'%')))
        return [{'id': user.id, 'name': user.name, 'email': user.email, 'phone': ''} for user in db.scalars(query)]


def list_bookings(limit=None):
    with SessionLocal() as db:
        query = select(Appointment, User).join(User, Appointment.user_id == User.id).order_by(Appointment.created_at.desc(), Appointment.id.desc())
        if limit:
            query = query.limit(limit)
        return [{'id': a.id, 'patient_name': user.name, 'patient_email': user.email,
            'doctor_name': doctor_label(a.doctor.name), 'specialty': a.doctor.specialty,
            'slot_time': to_ist(a.slot.starts_at), 'status': a.status} for a, user in db.execute(query)]


def update_booking_status(booking_id, status):
    status = status.strip().lower()
    if status not in {*ACTIVE_BOOKINGS, 'cancelled', 'completed'}:
        raise SchemaError('Invalid appointment status.')
    with SessionLocal.begin() as db:
        identity = db.get(Appointment, booking_id)
        if not identity:
            raise SchemaError('Appointment not found.')
        slot = db.scalar(select(Slot).where(Slot.id == identity.slot_id).with_for_update())
        appointment = db.scalar(select(Appointment).where(Appointment.id == booking_id).with_for_update().execution_options(populate_existing=True))
        occupied = bool(db.scalar(select(Appointment.id).where(Appointment.slot_id == slot.id,
            Appointment.id != booking_id, Appointment.status != 'cancelled').limit(1)))
        if status != 'cancelled' and appointment.status == 'cancelled':
            if occupied or slot.starts_at <= utcnow():
                raise SchemaError('This slot is no longer available. Create a new appointment instead.')
        appointment.status = status
        slot.booked = status != 'cancelled' or occupied
        sync_admin_status(db, booking_id, status)
