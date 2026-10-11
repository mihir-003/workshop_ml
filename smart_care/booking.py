from fastapi import HTTPException
from sqlalchemy import select, update
from clinic.models import Appointment, Doctor, Slot, utcnow
from smart_care.models import Episode, Visit
from smart_care.engine import unresolved_urgent


def guard_booking(db, user_id):
    ep = unresolved_urgent(db,user_id)
    if ep and ep.risk == 'urgent':
        raise HTTPException(422, 'This symptom check has urgent warning signs. Seek urgent in-person care instead of routine online booking.')


def book_visit(db, user_id, slot_id, reason, episode_id=None):
    guard_booking(db,user_id)
    ep = db.scalar(select(Episode).where(Episode.id==episode_id,Episode.user_id==user_id)) if episode_id else None
    if episode_id and not ep:
        raise HTTPException(404,'Symptom check not found.')
    if ep and (ep.status not in {'ready','reviewed'} or ep.risk=='urgent'):
        raise HTTPException(422,'Finish the symptom check before booking. Urgent cases require in-person care.')
    slot = db.get(Slot,slot_id)
    if ep and slot and ep.specialty and slot.doctor.specialty != ep.specialty:
        raise HTTPException(422,'This slot does not match the suggested department. Start a separate direct booking if you have a clinician referral.')
    result = db.execute(update(Slot).where(Slot.id==slot_id,Slot.booked.is_(False),Slot.starts_at>utcnow(),
            Slot.doctor_id.in_(select(Doctor.id).where(Doctor.active.is_(True)))).values(booked=True))
    if result.rowcount != 1:
        db.rollback()
        return None
    slot = db.get(Slot,slot_id)
    appt = Appointment(user_id=user_id,doctor_id=slot.doctor_id,slot_id=slot.id,
                       reason=((ep.profile.get('primary_symptom') if ep else reason) or 'Consultation')[:500],status='booked')
    db.add(appt); db.flush()
    if ep:
        db.add(Visit(appointment_id=appt.id,episode_id=ep.id,brief_snapshot=ep.brief))
    db.commit(); db.refresh(appt)
    return appt
