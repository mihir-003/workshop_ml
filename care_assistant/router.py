"""HTTP validation and authentication for the clinic assistant."""
from io import BytesIO
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from clinic.database import get_db
from clinic.security import check_csrf, check_origin, current_session, require_session
from care_assistant import llm, repository as records, service
from care_assistant.presentation import clinic_time, doctor_label

router = APIRouter(prefix='/assistant', tags=['Assistant'])
logger = logging.getLogger(__name__)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class BookingInput(BaseModel):
    slot_id: int = Field(gt=0)
    reason: str = Field(default='Consultation', max_length=500)


def _authorized(request, db):
    session = require_session(request, db)
    check_origin(request)
    check_csrf(request, session)
    return session


@router.get('/me')
def me(request: Request, db: Session = Depends(get_db)):
    session = current_session(request, db)
    if not session:
        return {'authenticated': False}
    return {'authenticated': True, 'name': session.user.name, 'csrf_token': session.csrf_token,
            'history': records.patient_history(db, session.user_id)}


@router.post('/chat')
def chat(payload: ChatInput, request: Request, db: Session = Depends(get_db)):
    session = _authorized(request, db)
    if not payload.message.strip():
        raise HTTPException(422, 'Enter a message.')
    try:
        return service.handle_chat(db, session, payload.message.strip())
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        logger.warning('Assistant reply failed: %s', type(exc).__name__)
        raise HTTPException(503, 'Groq could not reply. Check GROQ_API_KEY and GROQ_TEXT_MODEL, then try again.') from exc
    except Exception as exc:
        from groq import APIError
        if not isinstance(exc, APIError):
            raise
        db.rollback()
        logger.warning('Groq request failed: %s', type(exc).__name__)
        raise HTTPException(503, 'Groq is unavailable. Please try again shortly. Doctor availability and cancellation still work.') from exc


@router.get('/slots')
def slots(request: Request, specialty: str | None = None, doctor_id: int | None = None, db: Session = Depends(get_db)):
    require_session(request, db)
    return {'slots': records.available_slots(db, specialty, doctor_id)}


@router.post('/bookings')
@router.post('/book', include_in_schema=False)
def book(payload: BookingInput, request: Request, db: Session = Depends(get_db)):
    session = _authorized(request, db)
    appointment = records.book_slot(db, session.user_id, payload.slot_id, payload.reason)
    if not appointment:
        raise HTTPException(409, 'That slot is no longer available. Ask for available slots again.')
    result = records.appointment_dict(appointment)
    return {**result, 'ok': True, 'appointment': result, 'reply': f"Booked appointment #{result['id']} with {doctor_label(result['doctor'])} on {clinic_time(result['starts_at'])}."}


@router.post('/bookings/{appointment_id}/cancel')
def cancel(appointment_id: int, request: Request, db: Session = Depends(get_db)):
    session = _authorized(request, db)
    result = records.cancel_booking(db, session.user_id, appointment_id)
    if not result:
        raise HTTPException(404, 'No cancellable upcoming appointment found.')
    state = records.get_state(db, session.id)
    state.pop('cancel_choices', None)
    records.save_state(db, session.id, state)
    db.commit()
    return {'ok': True, 'appointment': result, 'reply': f"Cancelled appointment #{result['id']} with {doctor_label(result['doctor'])} on {clinic_time(result['starts_at'])}."}


@router.post('/photo')
async def photo(request: Request, image: UploadFile = File(...), message: str = Form(''), consent: bool = Form(False), db: Session = Depends(get_db)):
    session = _authorized(request, db)
    if not consent:
        raise HTTPException(400, 'Consent is required before sending an image to Groq.')
    if len(message) > 2000:
        raise HTTPException(422, 'Message is too long.')
    data = await image.read(4*1024*1024+1)
    if len(data) > 4*1024*1024:
        raise HTTPException(413, 'Use an image smaller than 4 MB.')
    try:
        with Image.open(BytesIO(data)) as picture:
            mime = Image.MIME.get(picture.format)
            if mime not in {'image/jpeg', 'image/png', 'image/webp'} or picture.width*picture.height > 16_000_000:
                raise ValueError()
            picture.verify()
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, 'Use a valid JPEG, PNG or WebP image up to 16 megapixels.')
    try:
        # Sync SDK calls run off the event loop.
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(llm.analyze, message, records.active_specialties(db), data, mime)
    except Exception as exc:
        logger.warning('Photo analysis failed: %s', type(exc).__name__)
        raise HTTPException(503, 'Groq photo analysis is unavailable. Check your vision model setting and try again.') from exc
    response = {'reply': result['advice'], 'specialty': result['specialty'], 'urgent': result['urgent']}
    if not result['urgent'] and result['specialty']:
        response['slots'] = records.available_slots(db, result['specialty'])
        state = records.get_state(db, session.id)
        state.update({'specialty': result['specialty'], 'doctor_id': None, 'date': None})
        records.save_state(db, session.id, state)
    records.remember_chat(db, session.user_id, message or '[Injury photo]', response['reply'], result['specialty'])
    return response
