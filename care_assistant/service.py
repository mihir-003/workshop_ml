"""Chat intent routing, with explicit patient-authorized appointment operations."""
import re
from datetime import datetime, time, timedelta

from sqlalchemy import select
from clinic.models import Doctor, utcnow
from clinic.slot_service import to_ist, to_utc
from care_assistant import llm, repository as records
from care_assistant.presentation import clinic_time, doctor_label


def _cancel_intent(message):
    lower = message.lower()
    if re.search(r"\b(don't|do not|dont|never|not|no)\b[^.!?;,\n]{0,35}\bcancel\b", lower) or re.search(r'\b(no|without)\s+cancell?ation\b', lower):
        return False
    if re.search(r'\b(how|why|what happens|what if|if i)\b.*\bcancel\b', lower):
        return False
    return bool(re.search(r'\b(cancel|cancell?ation)\b', lower))


def _date_range(message):
    local_today = to_ist(utcnow()).date()
    lower = message.lower()
    if re.search(r'\btomorrow\b', lower):
        day = local_today + timedelta(days=1)
    elif re.search(r'\btoday\b', lower):
        day = local_today
    else:
        match = re.search(r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b', message)
        if not match:
            return None, None, None
        try:
            day = datetime.strptime(match[0], '%Y-%m-%d' if '-' in match[0] else '%d/%m/%Y').date()
        except ValueError:
            raise ValueError('Please use a valid date, such as YYYY-MM-DD or DD/MM/YYYY.')
    start = to_utc(datetime.combine(day, time.min))
    return start, start + timedelta(days=1), day.isoformat()


def _doctor_id(db, message):
    lower = message.lower()
    matches = []
    for doctor in db.scalars(select(Doctor).where(Doctor.active.is_(True))):
        name = re.sub(r'^(?:dr\.?\s*)+', '', doctor.name.lower()).strip()
        if len(name) >= 3 and re.search(r'\b'+re.escape(name)+r'\b', lower):
            matches.append(doctor.id)
    return matches[0] if len(matches) == 1 else None


def _cancel(db, user_id, message, state):
    bookings = records.upcoming_bookings(db, user_id)
    doctor_id = _doctor_id(db, message)
    if doctor_id:
        bookings = [a for a in bookings if a['doctor_id'] == doctor_id]
    explicit = re.search(r'\b(?:appointment|booking)\s*(?:number\s*)?#?\s*(\d+)\b|\bcancel\s+#(\d+)\b', message.lower())
    selected = int(next(g for g in explicit.groups() if g)) if explicit else None
    if selected is None and state.get('cancel_choices') and message.strip().isdigit():
        number = int(message.strip())
        choices = state['cancel_choices']
        selected = choices[number-1] if 1 <= number <= len(choices) else -1
    if selected is not None:
        if selected not in {a['id'] for a in bookings}:
            return {'reply': 'That is not one of your upcoming appointments. Choose one of the appointments below.', 'appointments': bookings, 'action': 'choose_cancel'}
        result = records.cancel_booking(db, user_id, selected)
        state.pop('cancel_choices', None)
        if result:
            return {'reply': f"Cancelled appointment #{result['id']} with {doctor_label(result['doctor'])} on {clinic_time(result['starts_at'])}.",
                    'action': 'cancelled', 'appointment': result}
        return {'reply': 'That appointment can no longer be cancelled. Your appointment list has been refreshed.',
                'appointments': records.upcoming_bookings(db, user_id)}
    if not bookings:
        state.pop('cancel_choices', None)
        return {'reply': 'You have no upcoming appointment to cancel.', 'appointments': []}
    if len(bookings) == 1:
        return _cancel(db, user_id, f"cancel appointment #{bookings[0]['id']}", state)
    state['cancel_choices'] = [a['id'] for a in bookings]
    lines = [f"{i}. Appointment #{a['id']} — {doctor_label(a['doctor'])}, {clinic_time(a['starts_at'])}" for i, a in enumerate(bookings, 1)]
    return {'reply': 'Which appointment should I cancel? Reply with the list number or use a Cancel button.\n'+'\n'.join(lines),
            'appointments': bookings, 'action': 'choose_cancel'}


def _availability(db, message, state, specialty=None, doctor_id=None):
    after, before, day = _date_range(message)
    if not day and re.fullmatch(r'(?:yes|ok|okay|show(?: me)?(?: slots| times)?|which time|what time|slots|appointment)[.!?\s]*', message.lower()):
        day = state.get('date')
        if day:
            after, before, _ = _date_range(day)
    slots = records.available_slots(db, specialty, doctor_id, after=after, before=before)
    state.update({'specialty': specialty, 'doctor_id': doctor_id, 'date': day})
    qualifier = f' for {specialty}' if specialty else ''
    qualifier += f' on {day} (IST)' if day else ''
    return {'reply': f"Here are the available appointments{qualifier}. Choose a time to book." if slots else f"There are no available future slots{qualifier}. You can ask for another date or doctor.",
            'specialty': specialty, 'slots': slots, 'action': 'availability'}


def handle_chat(db, session, message):
    state = records.get_state(db, session.id)
    lower = message.lower().strip()
    if _cancel_intent(message) or (state.get('cancel_choices') and lower.isdigit()):
        response = _cancel(db, session.user_id, message, state)
    elif re.fullmatch(r'(never mind|nevermind|stop|no|no thanks)', lower) and state.get('cancel_choices'):
        state.pop('cancel_choices', None)
        response = {'reply': 'Okay. Let me know what else you need.', 'appointments': []}
    elif re.search(r'\b(my|our)\s+(?:upcoming\s+)?(?:appointments?|bookings?)\b', lower):
        state.pop('cancel_choices', None)
        bookings = records.upcoming_bookings(db, session.user_id)
        response = {'reply': 'Here are your upcoming appointments. You can cancel any one here.' if bookings else 'You have no upcoming appointments. Ask for an available doctor to book one.',
                    'appointments': bookings, 'action': 'appointments'}
    else:
        state.pop('cancel_choices', None)
        specialties = records.all_specialties(db)
        specialty = llm.specialty_hint(message, specialties)
        doctor_id = _doctor_id(db, message)
        discussing_care = bool(re.search(r'\b(told|said|prescribed|advised|diagnosed)\b', lower))
        clinic_request = bool(specialty or doctor_id or re.search(r'\b(doctors?|appointments?|bookings?|slots?|specialists?|available|availability)\b', lower))
        request_words = bool(re.search(r'\b(any|available|availability|find|show|need|want|book|have|see|consult|when|which|doctors?|appointments?|bookings?|slots?)\b', lower))
        bare_specialist = bool(specialty or doctor_id) and len(lower.split()) <= 5
        asks_availability = not discussing_care and clinic_request and (request_words or bare_specialist)
        follow_up = bool(state.get('specialty') or state.get('doctor_id')) and bool(re.fullmatch(r'(yes|ok|okay|show(?: me)?(?: slots| times)?|which time|what time|tomorrow|today)[.!?\s]*', lower))
        if llm.emergency(message):
            response = {'reply': 'Seek urgent in-person medical care now. Do not wait for a routine online appointment.', 'urgent': True}
        elif asks_availability or follow_up:
            if not specialty and not re.search(r'\b(any|all|another|other)\s+(?:doctors?|specialists?)\b', lower):
                specialty = state.get('specialty') if follow_up or re.search(r'\b(slots?|appointments?|times?)\b', lower) else None
                doctor_id = doctor_id or (state.get('doctor_id') if follow_up else None)
            try:
                response = _availability(db, message, state, specialty, doctor_id)
            except ValueError as exc:
                response = {'reply': str(exc)}
        else:
            result = llm.converse(message, records.active_specialties(db), records.recent_chat(db, session.user_id), records.patient_history(db, session.user_id))
            response = dict(result)
            if result['specialty']:
                state.update({'specialty': result['specialty'], 'doctor_id': None, 'date': None})
            if result['intent'] in {'find_doctor', 'find_slot', 'booking'} and not result['urgent']:
                response = _availability(db, message, state, result['specialty'])
    records.save_state(db, session.id, state)
    records.remember_chat(db, session.user_id, message, response['reply'], response.get('specialty'))
    return response
