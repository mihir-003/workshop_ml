from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clinic import assistant, service
from clinic.database import get_db
from clinic.models import ChatMessage, User
from clinic.security import COOKIE, check_csrf, check_origin, create_session, current_session, hash_password, require_session, set_auth_cookie, verify_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def auth_page(request, page, error=None, status_code=200):
    return templates.TemplateResponse(request, page, {"error": error}, status_code=status_code)


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return auth_page(request, "signup.html")


@router.post("/signup", response_class=HTMLResponse)
def signup(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    check_origin(request)
    name, email = name.strip(), email.strip().lower()
    if not (2 <= len(name) <= 100) or len(email) > 255 or "@" not in email or not (12 <= len(password) <= 128):
        return auth_page(request, "signup.html", "Enter a name, valid email and a password of 12–128 characters.", 400)
    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return auth_page(request, "signup.html", "This email already has an account. Please log in.", 400)
    response = RedirectResponse("/", status_code=303)
    set_auth_cookie(response, create_session(db, user.id))
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return auth_page(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    check_origin(request)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        return auth_page(request, "login.html", "Incorrect email or password.", 401)
    response = RedirectResponse("/", status_code=303)
    set_auth_cookie(response, create_session(db, user.id))
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    check_origin(request)
    session = require_session(request, db)
    check_csrf(request, session)
    db.delete(session)
    db.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    from care_assistant.router import me as assistant_me
    return assistant_me(request, db)


@router.get("/api/slots")
def slots(request: Request, specialty: str | None = None, doctor_id: int | None = None, db: Session = Depends(get_db)):
    from care_assistant.router import slots as assistant_slots
    return assistant_slots(request, specialty, doctor_id, db)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/api/chat")
def chat(payload: ChatInput, request: Request, db: Session = Depends(get_db)):
    from care_assistant.router import ChatInput as AssistantChatInput, chat as assistant_chat
    return assistant_chat(AssistantChatInput(message=payload.message), request, db)


@router.post("/api/chat/photo")
async def photo_chat(request: Request, image: UploadFile = File(...), message: str = Form(""), consent: bool = Form(False), db: Session = Depends(get_db)):
    from care_assistant.router import photo as assistant_photo
    return await assistant_photo(request, image, message, consent, db)


class BookingInput(BaseModel):
    slot_id: int = Field(gt=0)
    reason: str = Field(default="Consultation", max_length=500)


@router.post("/api/bookings")
def book(payload: BookingInput, request: Request, db: Session = Depends(get_db)):
    from care_assistant.router import BookingInput as AssistantBookingInput, book as assistant_book
    return assistant_book(AssistantBookingInput(slot_id=payload.slot_id, reason=payload.reason), request, db)


@router.post("/api/bookings/{appointment_id}/cancel")
def cancel(appointment_id: int, request: Request, db: Session = Depends(get_db)):
    from care_assistant.router import cancel as assistant_cancel
    return assistant_cancel(appointment_id, request, db)
