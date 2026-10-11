from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from clinic.admin_security import COOKIE_NAME, read_session_token
from clinic.database import SessionLocal
from clinic.models import Doctor, Treatment, User

router = APIRouter(prefix="/admin/treatments", tags=["Admin Treatments"])
templates = Jinja2Templates(directory="templates")


def _authorized(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    return bool(token and read_session_token(token))


def _login():
    return RedirectResponse("/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
def treatment_page(request: Request):
    if not _authorized(request):
        return _login()
    with SessionLocal() as db:
        treatments = db.scalars(select(Treatment).order_by(Treatment.updated_at.desc())).all()
        users = db.scalars(select(User).order_by(User.name)).all()
        doctors = db.scalars(select(Doctor).where(Doctor.active.is_(True)).order_by(Doctor.name)).all()
        return templates.TemplateResponse(request, "admin/treatments.html", {
            "treatments": treatments,
            "users": users,
            "doctors": doctors,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        })


@router.post("/new")
def add_treatment(
    request: Request,
    user_id: int = Form(...),
    doctor_id: int = Form(...),
    condition: str = Form(...),
    summary: str = Form(""),
    ongoing: bool = Form(False),
):
    if not _authorized(request):
        return _login()
    try:
        with SessionLocal() as db:
            if not db.get(User, user_id) or not db.get(Doctor, doctor_id):
                raise ValueError("Select an existing patient and doctor.")
            record = Treatment(
                user_id=user_id,
                doctor_id=doctor_id,
                condition=condition.strip()[:200],
                summary=summary.strip()[:2000],
                ongoing=ongoing,
            )
            if not record.condition:
                raise ValueError("Condition is required.")
            db.add(record)
            db.commit()
        return RedirectResponse("/admin/treatments?message=Treatment+record+added", status_code=303)
    except Exception as exc:
        from urllib.parse import quote_plus
        return RedirectResponse(f"/admin/treatments?error={quote_plus(str(exc))}", status_code=303)


@router.post("/{treatment_id}/toggle")
def toggle_treatment(request: Request, treatment_id: int):
    if not _authorized(request):
        return _login()
    with SessionLocal() as db:
        record = db.get(Treatment, treatment_id)
        if record:
            record.ongoing = not record.ongoing
            db.commit()
    return RedirectResponse("/admin/treatments?message=Treatment+status+updated", status_code=303)
