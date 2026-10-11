from __future__ import annotations

import os
from datetime import date, datetime, time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from clinic.admin_db import init_admin_tables
from clinic.admin_repository import (
    SchemaError,
    bulk_create_slots,
    create_doctor,
    create_slot,
    dashboard_stats,
    delete_doctor,
    delete_slot,
    get_doctor,
    list_bookings,
    list_doctors,
    list_slots,
    list_users,
    update_booking_status,
    update_doctor,
    update_slot,
)
from clinic.admin_security import COOKIE_NAME, create_session_token, read_session_token, verify_password
from clinic.database import engine

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="templates")


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() == "true"


def _admin_payload(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_session_token(token)


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


def _context(request: Request, **kwargs):
    return {"request": request, "admin": _admin_payload(request), **kwargs}


def _flash_redirect(path: str, message: str = "", error: str = "") -> RedirectResponse:
    from urllib.parse import urlencode
    query = urlencode({k: v for k, v in {"message": message, "error": error}.items() if v})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    init_admin_tables()
    if _admin_payload(request):
        return RedirectResponse("/admin/dashboard", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    init_admin_tables()
    with engine.connect() as conn:
        admin = conn.execute(
            text("SELECT id, username, password_hash, is_active FROM admin_users WHERE username=:username LIMIT 1"),
            {"username": username.strip()},
        ).mappings().first()
    if not admin or not admin["is_active"] or not verify_password(password, admin["password_hash"]):
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"error": "Invalid admin username or password."},
            status_code=401,
        )
    response = RedirectResponse("/admin/dashboard", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(admin["id"], admin["username"]),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=8 * 60 * 60,
    )
    return response


@router.post("/logout")
async def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not _admin_payload(request):
        return _login_redirect()
    error = request.query_params.get("error", "")
    try:
        stats = dashboard_stats()
        recent = list_bookings(limit=8)
    except Exception as exc:
        stats = {"doctors": 0, "available_slots": 0, "bookings": 0, "users": 0}
        recent = []
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {"stats": stats, "recent_bookings": recent, "error": error},
    )


@router.get("/doctors", response_class=HTMLResponse)
async def admin_doctors(request: Request, q: str = ""):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        doctors = list_doctors(q)
        error = request.query_params.get("error", "")
    except Exception as exc:
        doctors, error = [], str(exc)
    return templates.TemplateResponse(request, "admin/doctors.html", {
        "doctors": doctors,
        "q": q,
        "message": request.query_params.get("message", ""),
        "error": error,
    })


@router.get("/doctors/new", response_class=HTMLResponse)
async def admin_new_doctor_page(request: Request):
    if not _admin_payload(request):
        return _login_redirect()
    return templates.TemplateResponse(request, "admin/doctor_form.html", {"doctor": None, "error": None})


@router.post("/doctors/new")
async def admin_new_doctor(
    request: Request,
    name: str = Form(...),
    specialty: str = Form(...),
    qualification: str = Form(""),
    experience_years: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    consultation_fee: str = Form(""),
    about: str = Form(""),
    is_active: bool = Form(False),
):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        create_doctor(name.strip(), specialty.strip(), {
            "qualification": qualification.strip(),
            "experience_years": int(experience_years) if experience_years.strip() else None,
            "phone": phone.strip(),
            "email": email.strip(),
            "consultation_fee": consultation_fee.strip() or None,
            "about": about.strip(),
            "is_active": is_active,
        })
        return _flash_redirect("/admin/doctors", "Doctor added successfully.")
    except Exception as exc:
        return templates.TemplateResponse(request, "admin/doctor_form.html", {"doctor": None, "error": str(exc)}, status_code=400)


@router.get("/doctors/{doctor_id}/edit", response_class=HTMLResponse)
async def admin_edit_doctor_page(request: Request, doctor_id: int):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        doctor = get_doctor(doctor_id)
        error = None
    except Exception as exc:
        doctor, error = None, str(exc)
    return templates.TemplateResponse(request, "admin/doctor_form.html", {"doctor": doctor, "error": error})


@router.post("/doctors/{doctor_id}/edit")
async def admin_edit_doctor(
    request: Request,
    doctor_id: int,
    name: str = Form(...),
    specialty: str = Form(...),
    qualification: str = Form(""),
    experience_years: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    consultation_fee: str = Form(""),
    about: str = Form(""),
    is_active: bool = Form(False),
):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        update_doctor(doctor_id, name.strip(), specialty.strip(), {
            "qualification": qualification.strip(),
            "experience_years": int(experience_years) if experience_years.strip() else None,
            "phone": phone.strip(),
            "email": email.strip(),
            "consultation_fee": consultation_fee.strip() or None,
            "about": about.strip(),
            "is_active": is_active,
        })
        return _flash_redirect("/admin/doctors", "Doctor updated successfully.")
    except Exception as exc:
        doctor = {"id": doctor_id, "name": name, "specialty": specialty, "profile": {
            "qualification": qualification, "experience_years": experience_years, "phone": phone,
            "email": email, "consultation_fee": consultation_fee, "about": about, "is_active": is_active,
        }}
        return templates.TemplateResponse(request, "admin/doctor_form.html", {"doctor": doctor, "error": str(exc)}, status_code=400)


@router.post("/doctors/{doctor_id}/delete")
async def admin_delete_doctor(request: Request, doctor_id: int):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        delete_doctor(doctor_id)
        return _flash_redirect("/admin/doctors", "Doctor removed.")
    except Exception as exc:
        return _flash_redirect("/admin/doctors", error=str(exc))


@router.get("/slots", response_class=HTMLResponse)
async def admin_slots(request: Request, doctor_id: int | None = None):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        doctors = list_doctors()
        slots = list_slots(doctor_id)
        error = request.query_params.get("error", "")
    except Exception as exc:
        doctors, slots, error = [], [], str(exc)
    return templates.TemplateResponse(request, "admin/slots.html", {
        "doctors": doctors,
        "slots": slots,
        "selected_doctor_id": doctor_id,
        "message": request.query_params.get("message", ""),
        "error": error,
    })


@router.post("/slots/new")
async def admin_add_slot(
    request: Request,
    doctor_id: int = Form(...),
    start_time: str = Form(...),
    duration_minutes: int = Form(30),
):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        create_slot(doctor_id, datetime.fromisoformat(start_time), duration_minutes)
        return _flash_redirect("/admin/slots", "Slot added successfully.")
    except Exception as exc:
        return _flash_redirect("/admin/slots", error=str(exc))


@router.post("/slots/bulk")
async def admin_bulk_slots(
    request: Request,
    doctor_id: int = Form(...),
    slot_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    duration_minutes: int = Form(30),
):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        count = bulk_create_slots(
            doctor_id,
            date.fromisoformat(slot_date),
            time.fromisoformat(start_time),
            time.fromisoformat(end_time),
            duration_minutes,
        )
        return _flash_redirect("/admin/slots", f"{count} slots generated successfully.")
    except Exception as exc:
        return _flash_redirect("/admin/slots", error=str(exc))


@router.post("/slots/{slot_id}/edit")
async def admin_edit_slot(
    request: Request,
    slot_id: int,
    doctor_id: int = Form(...),
    start_time: str = Form(...),
    duration_minutes: int = Form(30),
):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        update_slot(slot_id, doctor_id, datetime.fromisoformat(start_time), duration_minutes)
        return _flash_redirect("/admin/slots", "Slot updated.")
    except Exception as exc:
        return _flash_redirect("/admin/slots", error=str(exc))


@router.post("/slots/{slot_id}/delete")
async def admin_delete_slot(request: Request, slot_id: int):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        delete_slot(slot_id)
        return _flash_redirect("/admin/slots", "Slot removed.")
    except Exception as exc:
        return _flash_redirect("/admin/slots", error=str(exc))


@router.get("/appointments", response_class=HTMLResponse)
async def admin_appointments(request: Request):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        bookings = list_bookings()
        error = request.query_params.get("error", "")
    except Exception as exc:
        bookings, error = [], str(exc)
    return templates.TemplateResponse(request, "admin/appointments.html", {
        "bookings": bookings,
        "message": request.query_params.get("message", ""),
        "error": error,
    })


@router.post("/appointments/{booking_id}/status")
async def admin_appointment_status(request: Request, booking_id: int, status: str = Form(...)):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        update_booking_status(booking_id, status)
        return _flash_redirect("/admin/appointments", "Appointment status updated.")
    except Exception as exc:
        return _flash_redirect("/admin/appointments", error=str(exc))


@router.get("/patients", response_class=HTMLResponse)
async def admin_patients(request: Request, q: str = ""):
    if not _admin_payload(request):
        return _login_redirect()
    try:
        users = list_users(q)
        error = request.query_params.get("error", "")
    except Exception as exc:
        users, error = [], str(exc)
    return templates.TemplateResponse(request, "admin/patients.html", {
        "users": users,
        "q": q,
        "error": error,
    })
