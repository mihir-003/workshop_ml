"""UTC slot lifecycle shared by the chatbot, admin pages and startup worker."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from sqlalchemy import MetaData, Table, exists, inspect, select, update
from clinic.database import SessionLocal
from clinic.models import Appointment, Doctor, Slot, utcnow

IST = timezone(timedelta(hours=5, minutes=30))


def to_utc(value):
    """Admin datetime-local inputs are IST; the existing database stores naive UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def to_ist(value):
    return value.replace(tzinfo=timezone.utc).astimezone(IST).replace(tzinfo=None) if value else None


def expire_slots(db, now=None):
    now = now or utcnow()
    # Older admin versions stored inactivity only in their profile table.
    if inspect(db.connection()).has_table('admin_doctor_profiles'):
        profiles = Table('admin_doctor_profiles', MetaData(), autoload_with=db.connection())
        db.execute(update(Doctor).where(Doctor.active.is_(True), Doctor.id.in_(
            select(profiles.c.doctor_id).where(profiles.c.is_active.is_(False)))).values(active=False))
    # Appointment-linked rows keep their foreign keys and remain in visit history.
    referenced = exists(select(Appointment.id).where(Appointment.slot_id == Slot.id))
    rows = db.scalars(select(Slot).where(Slot.starts_at <= now, Slot.booked.is_(False), ~referenced).with_for_update()).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def future_slots(db, specialty=None, doctor_id=None, after=None, before=None, limit=30):
    expire_slots(db)
    query = select(Slot).join(Doctor).where(Slot.booked.is_(False), Slot.starts_at > utcnow(), Doctor.active.is_(True))
    if specialty:
        query = query.where(Doctor.specialty == specialty)
    if doctor_id:
        query = query.where(Doctor.id == doctor_id)
    if after:
        query = query.where(Slot.starts_at >= after)
    if before:
        query = query.where(Slot.starts_at < before)
    return db.scalars(query.order_by(Slot.starts_at, Slot.id).limit(limit)).all()


def validate_slot(db, doctor_id, start, minutes, exclude=None):
    if not 5 <= minutes <= 240:
        raise ValueError('Duration must be between 5 and 240 minutes.')
    doctor = db.scalar(select(Doctor).where(Doctor.id == doctor_id).with_for_update())
    if not doctor or not doctor.active:
        raise ValueError('Select an active doctor.')
    start = to_utc(start)
    if start <= utcnow():
        raise ValueError('Choose a future slot in IST.')
    end = start + timedelta(minutes=minutes)
    query = select(Slot.id).where(Slot.doctor_id == doctor_id, Slot.starts_at < end, Slot.ends_at > start)
    if exclude:
        query = query.where(Slot.id != exclude)
    if db.scalar(query.limit(1)):
        raise ValueError('This time overlaps an existing slot for the doctor.')
    return start, end


def run_cleanup():
    with SessionLocal() as db:
        expire_slots(db)


async def start_slot_cleanup():
    async def worker():
        while True:
            try:
                await asyncio.to_thread(run_cleanup)
            except Exception:
                # Reads/bookings still apply UTC filtering if a cleanup attempt fails.
                import logging
                logging.getLogger(__name__).warning('Slot cleanup failed; retrying in 30 seconds.', exc_info=True)
            await asyncio.sleep(30)
    return asyncio.create_task(worker(), name='expired-slot-cleanup')


async def stop_slot_cleanup(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def with_slot_cleanup(original):
    """Keep the clinic's existing startup, shutdown and yielded application state."""
    from contextlib import asynccontextmanager
    from inspect import isasyncgenfunction

    if isasyncgenfunction(original):
        original = asynccontextmanager(original)

    @asynccontextmanager
    async def managed(app):
        async with original(app) as state:
            task = await start_slot_cleanup()
            try:
                yield state
            finally:
                await stop_slot_cleanup(task)

    return managed
