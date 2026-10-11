"""One-chat, server-side MCP orchestration for the separate /newpage.html UI.

Security: no browser-selected tools for chat, RBAC checked on *every* call,
verified read results only, explicit confirm for all mutations, pending actions
are one-shot and bound to the authenticated login + CSRF session. State is
process-local and short-lived (intended for the project's single-worker server).
"""
import asyncio
import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from mcp_rbac.audit import record
from mcp_rbac.auth import Principal
from mcp_rbac.dispatch import invoke
from mcp_rbac.intents import parse, specialty_variants
from mcp_rbac.policy import permitted

IST = ZoneInfo('Asia/Kolkata')
SESSION_SECONDS = 20 * 60
CONFIRM_SECONDS = 5 * 60
MAX_SESSIONS = 500
WRITE_ACTIONS = frozenset({'book_slot', 'cancel_appointment', 'admin_add_slot',
                           'admin_set_status', 'admin_set_role'})
YES = frozenset({'yes', 'y', 'confirm', 'yes confirm', 'confirm it', 'go ahead',
                 'proceed', 'yes please', 'ok confirm', 'yes book it', 'yes cancel it',
                 'please confirm', 'do it'})
NO = frozenset({'no', 'n', 'cancel', 'stop', 'never mind', 'nevermind', 'do not',
                'dont', "don't", 'no thanks', 'abort', 'cancel action'})


@dataclass
class Conversation:
    role: str
    subject_id: int
    credential_hash: str
    last_seen: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_slots: list[dict] = field(default_factory=list)
    last_appointments: list[dict] = field(default_factory=list)
    last_doctors: list[dict] = field(default_factory=list)
    pending: dict | None = None
    draft: dict | None = None


_CONVERSATIONS: dict[str, Conversation] = {}


def _get_conversation(principal: Principal, credential: str, key: str | None):
    now = time.time()
    identity = hashlib.sha256(credential.encode()).hexdigest()
    for k, state in list(_CONVERSATIONS.items()):
        if now - state.last_seen > SESSION_SECONDS:
            _CONVERSATIONS.pop(k, None)
    c = _CONVERSATIONS.get(key or '')
    if c is None or (c.role, c.subject_id, c.credential_hash) != (principal.role, principal.subject_id, identity):
        key = secrets.token_urlsafe(24)
        c = Conversation(principal.role, principal.subject_id, identity)
        if len(_CONVERSATIONS) >= MAX_SESSIONS:
            oldest = min(_CONVERSATIONS, key=lambda k: _CONVERSATIONS[k].last_seen)
            _CONVERSATIONS.pop(oldest, None)
        _CONVERSATIONS[key] = c
    c.last_seen = now
    return key, c


def _answer(reply: str, status: str = 'OK', data=None, **extras):
    return {'status': status, 'reply': reply, 'data': data, **extras}


def _no(reply='NO — no matching verified record was found.'):
    return _answer(reply, 'NO')


async def _tool(actor: Principal, action: str, params: dict | None = None):
    # No bypasses: even follow-ups and confirmations go through the dispatcher.
    if not permitted(actor.role, action) or actor.role == 'system':
        record(actor.role, actor.subject_id, action, 'denied')
        return {'status': 'DENIED', 'reply': 'Permission denied.', 'data': None}
    try:
        result = await invoke(actor, action, params or {})
    except (ValueError, TypeError) as exc:
        record(actor.role, actor.subject_id, action, 'invalid')
        return {'status': 'INVALID', 'reply': str(exc), 'data': None}
    except Exception:
        record(actor.role, actor.subject_id, action, 'error')
        raise
    record(actor.role, actor.subject_id, action, result['status'].lower())
    return result


def _display_time(value: str):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('UTC'))
        return stamp.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')
    except (ValueError, AttributeError):
        return 'Time unavailable'


def _date_time(message: str) -> str | None:
    """Parse a clearly specified date + time for admin slot creation (IST)."""
    s = message.casefold()
    today = datetime.now(IST).date()
    if 'day after tomorrow' in s:
        day = today + timedelta(days=2)
    elif re.search(r'\btomorrow\b', s):
        day = today + timedelta(days=1)
    elif re.search(r'\btoday\b', s):
        day = today
    else:
        day = None
        iso = re.search(r'\b(20\d\d)-(\d{1,2})-(\d{1,2})\b', s)
        slash = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d\d)\b', s)
        words = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(20\d\d))?\b', s)
        month_first = re.search(r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b', s)
        months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        try:
            if iso:
                day = date(*map(int, iso.groups()))
            elif slash:
                d, m, y = map(int, slash.groups())
                day = date(y, m, d)  # DD/MM/YYYY (India)
            elif words or month_first:
                match = words or month_first
                d, m, y = (words.group(1), words.group(2), words.group(3)) if words else (month_first.group(2), month_first.group(1), month_first.group(3))
                day = date(int(y) if y else today.year, months[m[:3]], int(d))
                if not y and day < today:
                    day = date(today.year + 1, months[m[:3]], int(d))
        except ValueError:
            return None
    hour, minute = None, 0
    clock = re.search(r'\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?!\w)', s)
    clock_24 = re.search(r'\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b', s)
    if clock:
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        hour = hour % 12 + (12 if clock.group(3).startswith('p') else 0)
    elif clock_24:
        hour, minute = map(int, clock_24.groups())
    if day is None or hour is None:
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).isoformat()


def _duration(message: str) -> int | None:
    match = re.search(r'\b(\d{1,3})\s*(?:min(?:ute)?s?)\b', message.casefold())
    return int(match.group(1)) if match else None


def _index(message: str) -> int | None:
    m = re.search(r'\b(?:option|number|no\.?|#)\s*#?\s*(\d+)\b', message.casefold())
    if m:
        return int(m.group(1))
    m = re.fullmatch(r'\s*(\d+)\s*', message)
    return int(m.group(1)) if m else None


def _positive_id(message: str, label: str) -> int | None:
    m = re.search(r'\b' + re.escape(label) + r'\s*(?:id|number|no\.?|#)?\s*#?\s*(\d+)\b', message.casefold())
    return int(m.group(1)) if m else None


def _find_by_name(message: str, doctors: list[dict]) -> list[dict]:
    s = message.casefold()
    return [doc for doc in doctors if (doc['name'].casefold() in s or
            # Accept "Jay Patel" for "Dr. Jay Patel", but not isolated common names.
            re.sub(r'^dr\.?\s*', '', doc['name'].casefold()) in s)]


def _slot_lines(slots: list[dict]) -> str:
    return '\n'.join(f"{i}. {x.get('doctor', 'Doctor')} ({x.get('specialty', 'Specialist')}) — {_display_time(x['starts_at'])} [slot #{x['slot_id']}]" for i, x in enumerate(slots, 1))


def _appointment_lines(rows: list[dict]) -> str:
    return '\n'.join(f"{i}. Appointment #{a['id']} — {a.get('doctor', 'Doctor')}, {_display_time(a['starts_at'])}, status: {a['status']}" for i, a in enumerate(rows, 1))


def _doctor_lines(rows: list[dict]) -> str:
    return '\n'.join(f"{i}. {d['name']} — {d['specialty']} (ID {d['id']}, {'active' if d['active'] else 'inactive'})" for i, d in enumerate(rows, 1))


def _pending(c: Conversation, action: str, params: dict, description: str):
    c.pending = {'action': action, 'params': params, 'expires': time.time() + CONFIRM_SECONDS}
    c.draft = None
    return _answer(description + '\n\nReply **confirm** to proceed, or **no** to cancel.', 'CONFIRM', action=action)


def _number_or_id(text: str, rows: list[dict], field: str):
    explicit = re.search(r'\b(?:slot|appointment|booking)\s*(?:id|number|no\.?|#)?\s*#?\s*(\d+)\b', text.casefold())
    if explicit:
        ident = int(explicit.group(1))
        return next((x for x in rows if x.get(field) == ident), None)
    n = _index(text)
    if n is None:
        match = re.search(r'\b(?:book|reserve|choose|select|pick)\s+(?:option\s+|number\s+)?(\d+)\b', text.casefold())
        if match:
            n = int(match.group(1))
    if n is not None and 1 <= n <= len(rows):
        return rows[n - 1]
    return None


async def _slots(actor: Principal, c: Conversation, message: str):
    variants = specialty_variants(message)
    # Search genuine variants separately: the DB contains e.g. "Dermatologist"
    # rather than the abstract label "Dermatology". Do not hallucinate records.
    combined = []
    seen = set()
    for specialty in variants or ('',):
        result = await _tool(actor, 'search_slots', {'specialty': specialty, 'limit': 30})
        if result['status'] not in {'OK', 'NO'}:
            return result
        for x in result.get('data') or []:
            if x['slot_id'] not in seen:
                combined.append(x)
                seen.add(x['slot_id'])
    combined.sort(key=lambda x: x['starts_at'])
    c.last_slots = combined[:30]
    if not c.last_slots:
        return _no('NO — there are no matching future available slots in the clinic database.')
    return _answer('Here are the verified available slots (India time):\n' + _slot_lines(c.last_slots)
                   + '\n\nReply "book 1", "book slot #ID", or "book that appointment" if only one is listed.',
                   data=c.last_slots)


async def _appointments(actor: Principal, c: Conversation, admin=False):
    action = 'admin_appointments' if admin else 'my_appointments'
    result = await _tool(actor, action)
    if result['status'] != 'OK':
        return _no('NO — no appointment records found.') if result['status'] == 'NO' else result
    if admin:
        rows = [x['appointment'] for x in result['data']]
    else:
        rows = result['data']
    c.last_appointments = rows
    return _answer('Verified appointments:\n' + _appointment_lines(rows), data=result['data'])


async def _doctors(actor: Principal, c: Conversation, search=''):
    result = await _tool(actor, 'admin_doctors', {'search': search})
    if result['status'] != 'OK':
        return _no('NO — no matching doctors in the database.') if result['status'] == 'NO' else result
    c.last_doctors = result['data']
    return _answer('Verified clinic doctors:\n' + _doctor_lines(c.last_doctors), data=result['data'])


async def _booking(actor: Principal, c: Conversation, message: str, params: dict):
    rows = c.last_slots
    chosen = None
    explicit_id = params.get('slot_id')
    if explicit_id is not None:
        chosen = next((x for x in rows if x['slot_id'] == explicit_id), None)
    else:
        chosen = _number_or_id(message, rows, 'slot_id')
        if chosen is None and len(rows) == 1:
            chosen = rows[0]
    if chosen is None and rows:
        ordinal = re.search(r'\b(first|second|third|fourth|last)\b', message.casefold())
        if ordinal:
            number = {'first': 0, 'second': 1, 'third': 2, 'fourth': 3, 'last': -1}[ordinal.group(1)]
            if -len(rows) <= number < len(rows):
                chosen = rows[number]
        if chosen is None:
            at = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', message.casefold())
            if at:
                hour = int(at.group(1)) % 12 + (12 if at.group(3) == 'pm' else 0)
                minute = int(at.group(2) or 0)
                matches = []
                for candidate in rows:
                    stamp = datetime.fromisoformat(candidate['starts_at'].replace('Z', '+00:00')).astimezone(IST)
                    if stamp.hour == hour and stamp.minute == minute:
                        matches.append(candidate)
                if len(matches) == 1:
                    chosen = matches[0]
    if chosen is None:
        return _answer('Please search availability first (e.g. "available dermatologist slots") and then say "book 1" or "book slot #ID". I will only offer a slot verified from the database.')
    # Availability can change: this still requires a fresh atomic DB check by book_slot.
    return _pending(c, 'book_slot', {'slot_id': chosen['slot_id']},
                    f"Book {chosen.get('doctor', 'this doctor')} on {_display_time(chosen['starts_at'])} (slot #{chosen['slot_id']})?")


async def _cancel(actor: Principal, c: Conversation, message: str, params: dict):
    result = await _tool(actor, 'my_appointments')
    if result['status'] != 'OK':
        return _no('NO — you have no appointments to cancel.') if result['status'] == 'NO' else result
    now = datetime.now(ZoneInfo('UTC'))
    possible = []
    for row in result['data']:
        try:
            when = datetime.fromisoformat(row['starts_at'].replace('Z', '+00:00'))
        except (ValueError, KeyError):
            continue
        if row.get('status') in {'booked', 'confirmed', 'pending'} and when > now:
            possible.append(row)
    if not possible:
        return _no('NO — you have no future, cancellable appointments.')
    selected = None
    requested = params.get('appointment_id')
    if requested is not None:
        selected = next((x for x in possible if x['id'] == requested), None)
    else:
        selected = _number_or_id(message, possible, 'id')
        if selected is None and len(possible) == 1:
            selected = possible[0]
    c.last_appointments = possible
    if selected is None:
        return _answer('Which appointment should I cancel?\n' + _appointment_lines(possible) + '\n\nReply "cancel appointment #ID".')
    return _pending(c, 'cancel_appointment', {'appointment_id': selected['id']},
                    f"Cancel appointment #{selected['id']} with {selected.get('doctor', 'your doctor')} on {_display_time(selected['starts_at'])}?")


async def _admin_slot(actor: Principal, c: Conversation, text: str, previous: dict | None = None):
    draft = dict(previous or {})
    result = await _tool(actor, 'admin_doctors')
    if result['status'] != 'OK':
        return result
    doctors = [d for d in result['data'] if d.get('active')]
    c.last_doctors = result['data']
    found = _find_by_name(text, doctors)
    explicit_id = _positive_id(text, 'doctor')
    if explicit_id is None and re.fullmatch(r'\s*\d+\s*', text) and 'doctor_id' not in draft:
        explicit_id = int(text.strip())
    if explicit_id:
        found = [d for d in doctors if d['id'] == explicit_id]
        if not found:
            return _no('NO — that doctor ID is not an active doctor in the database.')
    if len(found) == 1:
        draft['doctor_id'] = found[0]['id']
        draft['doctor_name'] = found[0]['name']
    elif len(found) > 1:
        c.draft = draft
        return _answer('Multiple doctors matched. Please specify the doctor ID:\n' + _doctor_lines(found))
    when = _date_time(text)
    if when:
        draft['starts_at'] = when
    minutes = _duration(text)
    if minutes is not None:
        draft['minutes'] = minutes
    if 'doctor_id' not in draft:
        c.draft = {'action': 'admin_add_slot', **draft}
        return _answer('Which doctor? Reply with their full name or ID:\n' + _doctor_lines(doctors[:30]))
    if 'starts_at' not in draft:
        c.draft = {'action': 'admin_add_slot', **draft}
        return _answer(f"What date and time for {draft['doctor_name']}? Example: '15 Oct 2026 at 11:00 AM' or 'tomorrow at 11 AM' (IST).")
    if 'minutes' not in draft:
        draft['minutes'] = 30
    if not 5 <= draft['minutes'] <= 240:
        c.draft = {'action': 'admin_add_slot', **draft}
        draft.pop('minutes', None)
        return _answer('Duration must be between 5 and 240 minutes. For example, reply "30 minutes".')
    return _pending(c, 'admin_add_slot', {k: draft[k] for k in ('doctor_id', 'starts_at', 'minutes')},
                    f"Create an availability slot for {draft['doctor_name']} on {_display_time(datetime.fromisoformat(draft['starts_at']).astimezone(ZoneInfo('UTC')).isoformat())}, duration {draft['minutes']} minutes?")


async def _admin_status(actor: Principal, c: Conversation, text: str, previous=None):
    draft = dict(previous or {})
    identifier = _positive_id(text, 'appointment') or _positive_id(text, 'booking')
    if identifier:
        draft['appointment_id'] = identifier
    status = re.search(r'\b(booked|confirmed|pending|cancelled|completed)\b', text.casefold())
    if status:
        draft['status'] = status.group(1)
    if 'appointment_id' not in draft:
        c.draft = {'action': 'admin_set_status', **draft}
        result = await _appointments(actor, c, admin=True)
        return _answer('Which appointment ID should I update?\n' + result['reply'])
    if 'status' not in draft:
        c.draft = {'action': 'admin_set_status', **draft}
        return _answer('What status? booked, confirmed, pending, cancelled or completed.')
    # Check the record exists before asking for approval. The MCP tool checks again on write.
    result = await _tool(actor, 'admin_appointments', {'limit': 50})
    if result['status'] != 'OK' or not any(x['appointment']['id'] == draft['appointment_id'] for x in result.get('data') or []):
        return _no('NO — that appointment was not found among the last 50 verified records.')
    return _pending(c, 'admin_set_status', {k: draft[k] for k in ('appointment_id', 'status')},
                    f"Set appointment #{draft['appointment_id']} to '{draft['status']}'?")


async def _admin_role(actor: Principal, c: Conversation, text: str, previous=None):
    draft = dict(previous or {})
    ident = _positive_id(text, 'admin') or _positive_id(text, 'account')
    if ident:
        draft['admin_id'] = ident
    m = re.search(r'\bsuper[ _-]?admin\b', text.casefold())
    if m:
        draft['role'] = 'super_admin'
    elif re.search(r'\b(?:to|as|role)\s+admin\b', text.casefold()) or re.fullmatch(r'\s*admin\s*', text.casefold()):
        draft['role'] = 'admin'
    if 'admin_id' not in draft:
        c.draft = {'action': 'admin_set_role', **draft}
        return _answer('Specify the admin account ID. Example: "admin #2".')
    if 'role' not in draft:
        c.draft = {'action': 'admin_set_role', **draft}
        return _answer('New role: admin or super_admin?')
    return _pending(c, 'admin_set_role', {k: draft[k] for k in ('admin_id', 'role')},
                    f"Change admin account #{draft['admin_id']} to role '{draft['role']}'?")


async def _process(actor: Principal, c: Conversation, message: str):
    text = message.strip()
    normalized = re.sub(r'\s+', ' ', text.casefold()).strip(' .!?')
    if normalized in NO:
        c.pending = None
        c.draft = None
        return _answer('Cancelled. No database changes were made.')
    if normalized in YES:
        pending = c.pending
        if not pending:
            return _answer('There is no action awaiting confirmation. Tell me what you would like to do.')
        c.pending = None  # one-shot: cannot replay "confirm" to perform the same write again
        if pending['expires'] < time.time():
            return _answer('Confirmation expired. Please request the action again; nothing was changed.')
        action = pending['action']
        if action not in WRITE_ACTIONS:
            return _answer('That action cannot be confirmed through chat.', 'DENIED')
        result = await _tool(actor, action, pending['params'])
        if result['status'] == 'NO':
            return _no('NO — the record is unavailable or has changed. No change was made; please check again.')
        if result['status'] == 'OK':
            if action == 'book_slot':
                c.last_slots = [s for s in c.last_slots if s['slot_id'] != pending['params']['slot_id']]
            return _answer('Confirmed. ' + result.get('reply', 'The action completed successfully.'), data=result.get('data'))
        return result
    if c.pending:
        c.pending = None  # a different instruction supersedes any unconfirmed write
    if c.draft:
        draft = c.draft
        c.draft = None
        if draft['action'] == 'admin_add_slot':
            return await _admin_slot(actor, c, text, draft)
        if draft['action'] == 'admin_set_status':
            return await _admin_status(actor, c, text, draft)
        if draft['action'] == 'admin_set_role':
            return await _admin_role(actor, c, text, draft)
    # Follow-up selection from a previously shown database result.
    if actor.role == 'user' and _index(text) and c.last_slots:
        return await _booking(actor, c, text, {})
    requested = parse(actor.role, text)
    if not requested:
        if actor.role == 'user':
            return _answer('I can check real appointment slots, book an available slot, show your appointments or profile, and cancel one of your bookings. Try "available dermatologist slots".')
        return _answer('I can show clinic doctors, appointments, statistics, add availability slots, and update booking status. Super Admin can also review MCP audit events and change admin roles. Try "add slot for Dr. Jay Patel tomorrow at 11 AM for 30 minutes".')
    action, params = requested
    if not permitted(actor.role, action):
        return _answer('You do not have permission for that action.', 'DENIED')
    if action == 'search_slots':
        return await _slots(actor, c, text)
    if action == 'book_slot':
        return await _booking(actor, c, text, params)
    if action == 'my_appointments':
        return await _appointments(actor, c)
    if action == 'cancel_appointment':
        return await _cancel(actor, c, text, params)
    if action == 'admin_doctors':
        return await _doctors(actor, c)
    if action == 'admin_appointments':
        return await _appointments(actor, c, admin=True)
    if action == 'admin_add_slot':
        return await _admin_slot(actor, c, text)
    if action == 'admin_set_status':
        return await _admin_status(actor, c, text, params)
    if action == 'admin_set_role':
        return await _admin_role(actor, c, text, params)
    result = await _tool(actor, action, params)
    if result['status'] == 'NO':
        return _no()
    if result['status'] != 'OK':
        return result
    if action == 'view_profile':
        p = result['data']
        return _answer(f"Your verified profile: {p['name']} (ID {p['id']}), email: {p['email']}.", data=p)
    if action == 'admin_stats':
        return _answer('Verified clinic totals:\n' + '\n'.join(f'{k.replace("_", " ").title()}: {v}' for k, v in result['data'].items()), data=result['data'])
    if action == 'admin_audit':
        events = result['data']
        lines = [f"Event #{event['id']}: {event['role']} #{event['actor_id']} — {event['action']} ({event['outcome']}), {event['created_at']}" for event in events]
        return _answer('Verified MCP audit events (newest first):\n' + '\n'.join(lines), data=events)
    return result


async def respond(actor: Principal, credential: str, message: str, conversation_id: str | None):
    key, c = _get_conversation(actor, credential, conversation_id)
    async with c.lock:
        response = await _process(actor, c, message)
        response['conversation_id'] = key
        return response
