"""Display helpers; stored names and UTC timestamps remain unchanged."""
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name='IST')


def doctor_label(name):
    clean = re.sub(r'^(?:dr\.?\s+)+', '', str(name).strip(), flags=re.I)
    return f'Dr. {clean}'


def clinic_time(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')
