"""Deterministic, allowlisted chat intent recognition. No model-generated SQL/actions.

The interpreter only proposes actions; the route and FastMCP dispatcher enforce
RBAC independently. Follow-up state and confirmation live in conversation.py.
"""
import re


SPECIALTIES = {
    'dermatolog': ('Dermatologist', 'Dermatology'),
    'skin': ('Dermatologist', 'Dermatology'),
    'neurolog': ('Neurology', 'Neurologist'),
    'brain': ('Neurology', 'Neurologist'),
    'dent': ('Dentist', 'Dentistry'),
    'teeth': ('Dentist', 'Dentistry'),
    'physician': ('Physician', 'General Medicine'),
    'general medicine': ('Physician', 'General Medicine'),
    'cardiolog': ('Cardiologist', 'Cardiology'),
    'gastro': ('Gastroenterologist', 'Gastroenterology'),
    'orthop': ('Orthopedics', 'Orthopedic'),
}


def specialty_variants(message: str) -> tuple[str, ...]:
    lower = message.casefold()
    for pattern, variants in SPECIALTIES.items():
        if pattern in lower:
            return variants
    return ()


def parse(role: str, message: str) -> tuple[str, dict] | None:
    """Return a role-appropriate action and explicit parameters, or None."""
    msg = message.strip().casefold()
    if not msg:
        return None
    if role == 'user':
        if re.search(r'\b(my profile|my account|who am i|profile details)\b', msg):
            return 'view_profile', {}
        if re.search(r'\b(my appointments|my bookings|booking history|appointment history|show (?:me )?my booking)', msg):
            return 'my_appointments', {}
        if re.search(r'\b(cancel|delete|remove)\b', msg) and re.search(r'\b(appointment|booking|reservation)\b', msg):
            match = re.search(r'(?:appointment|booking|reservation)\s*(?:id|number|no\.?|#)?\s*#?\s*(\d+)\b', msg)
            return 'cancel_appointment', {'appointment_id': int(match.group(1))} if match else {}
        if re.search(r'\b(book|reserve|schedule|confirm booking)\b', msg):
            match = re.search(r'\b(?:slot|appointment)\s*(?:id|number|no\.?|#)?\s*#?\s*(\d+)\b', msg)
            if not match:
                match = re.search(r'\bbook\s*#\s*(\d+)\b', msg)
            return 'book_slot', {'slot_id': int(match.group(1))} if match else {}
        if re.search(r'\b(available|availability|free|slots?|doctors?|specialist|appointment|timings?|consultation)\b', msg) or specialty_variants(msg):
            return 'search_slots', {}
    elif role in {'admin', 'super_admin'}:
        if role == 'super_admin' and re.search(r'\b(change|update|set|assign|promote|demote)\b', msg) and re.search(r'\b(role|super.?admin|permission)\b', msg):
            match = re.search(r'\b(?:admin|account|user)\s*(?:id|#)?\s*#?\s*(\d+)\b', msg)
            new_role = 'super_admin' if re.search(r'\bsuper[ _-]?admin\b', msg) else ('admin' if re.search(r'\b(?:to|as|role)\s+admin\b', msg) else None)
            return 'admin_set_role', dict((k, v) for k, v in {'admin_id': int(match.group(1)) if match else None, 'role': new_role}.items() if v is not None)
        if re.search(r'\b(add|create|new|open|schedule)\b', msg) and re.search(r'\b(slots?|availability|session|doctor timing)\b', msg):
            return 'admin_add_slot', {}
        if re.search(r'\b(update|change|set|mark)\b', msg) and re.search(r'\b(status|appointment|booking)\b', msg):
            match = re.search(r'\b(?:appointment|booking)\s*(?:id|#)?\s*#?\s*(\d+)\b', msg)
            status_match = re.search(r'\b(booked|confirmed|pending|cancelled|completed)\b', msg)
            return 'admin_set_status', dict((k, v) for k, v in {'appointment_id': int(match.group(1)) if match else None, 'status': status_match.group(1) if status_match else None}.items() if v is not None)
        if role == 'super_admin' and re.search(r'\baudit|activity log|tool log\b', msg):
            return 'admin_audit', {}
        if re.search(r'\b(stat|stats|statistics|dashboard|summary|totals?|counts?)\b', msg):
            return 'admin_stats', {}
        if re.search(r'\b(appointments|bookings|reservations)\b', msg):
            return 'admin_appointments', {}
        if re.search(r'\b(doctors?|specialties|physicians?|staff)\b', msg) or specialty_variants(msg):
            return 'admin_doctors', {}
    return None
