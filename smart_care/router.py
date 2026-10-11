from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from clinic.database import get_db
from clinic.models import Appointment, Doctor, Treatment, utcnow
from clinic.security import require_session, current_session, check_origin, check_csrf
from smart_care.models import Episode, Visit, Progress, DoctorAccess
from smart_care import engine

router = APIRouter(tags=['Smart Care'])
templates = Jinja2Templates(directory='templates')


def write_session(request,db):
    session = require_session(request,db)
    check_origin(request); check_csrf(request,session)
    return session


def doctor_session(request,db):
    session = require_session(request,db)
    access = db.scalar(select(DoctorAccess).join(Doctor,Doctor.id==DoctorAccess.doctor_id).where(DoctorAccess.user_id==session.user_id,Doctor.active.is_(True)))
    if not access:
        raise HTTPException(403,'This account has no active doctor dashboard access.')
    return session,access.doctor_id


@router.get('/care')
def patient_page(request:Request,db:Session=Depends(get_db)):
    if not current_session(request,db):
        return RedirectResponse('/login',303)
    return templates.TemplateResponse(request,'care_dashboard.html',{'doctor_mode':False})


@router.get('/doctor')
def doctor_page(request:Request,db:Session=Depends(get_db)):
    if not current_session(request,db):
        return RedirectResponse('/login',303)
    doctor_session(request,db)
    return templates.TemplateResponse(request,'care_dashboard.html',{'doctor_mode':True})


def progress_dict(p):
    return {'id':p.id,'status':p.status,'severity':p.severity,'note':p.note,'created_at':p.created_at.isoformat()+'Z'}


@router.get('/care/api/dashboard')
def dashboard(request:Request,db:Session=Depends(get_db)):
    session = require_session(request,db)
    episodes = db.scalars(select(Episode).where(Episode.user_id==session.user_id).order_by(Episode.id.desc()).limit(30)).all()
    treatments = db.scalars(select(Treatment).where(Treatment.user_id==session.user_id).order_by(Treatment.updated_at.desc()).limit(30)).all()
    appointments = db.scalars(select(Appointment).where(Appointment.user_id==session.user_id).order_by(Appointment.id.desc()).limit(30)).all()
    return {'name':session.user.name,'csrf_token':session.csrf_token,
        'doctor_access':bool(db.scalar(select(DoctorAccess).where(DoctorAccess.user_id==session.user_id))),
        'episodes':[engine.episode_dict(ep) for ep in episodes],
        'appointments':[{'id':a.id,'doctor':a.doctor.name,'specialty':a.doctor.specialty,'starts_at':a.slot.starts_at.isoformat()+'Z','status':a.status,'reason':a.reason} for a in appointments],
        'treatments':[{'id':t.id,'condition':t.condition,'summary':t.summary,'doctor':t.doctor.name,'ongoing':t.ongoing,
            'progress':[progress_dict(p) for p in db.scalars(select(Progress).where(Progress.treatment_id==t.id,Progress.user_id==session.user_id).order_by(Progress.id.desc()).limit(30))]} for t in treatments]}


@router.get('/care/api/episodes/{episode_id}')
def episode_detail(episode_id:int,request:Request,db:Session=Depends(get_db)):
    session=require_session(request,db)
    ep=db.scalar(select(Episode).where(Episode.id==episode_id,Episode.user_id==session.user_id))
    if not ep: raise HTTPException(404,'Symptom check not found.')
    return {'episode':engine.episode_dict(ep),'transcript':ep.transcript,'similar_cases':engine.similar_cases(db,ep)}


class ProgressInput(BaseModel):
    status: Literal['better','same','worse']
    severity: int | None = Field(default=None,ge=0,le=10)
    note: str = Field(default='',max_length=1000)


@router.post('/care/api/treatments/{treatment_id}/progress')
def progress(treatment_id:int,payload:ProgressInput,request:Request,db:Session=Depends(get_db)):
    session=write_session(request,db)
    treatment=db.scalar(select(Treatment).where(Treatment.id==treatment_id,Treatment.user_id==session.user_id))
    if not treatment: raise HTTPException(404,'Treatment not found.')
    p=Progress(user_id=session.user_id,treatment_id=treatment.id,status=payload.status,severity=payload.severity,note=payload.note.strip())
    db.add(p)
    danger=engine.affirmative_danger(payload.note)
    if danger:
        engine.save_warning(db, session.user_id, payload.note, "Warning sign reported in treatment progress: " + danger)
    db.commit(); db.refresh(p)
    guidance='Seek urgent in-person medical care now.' if danger else ('Contact your treating clinician promptly if symptoms are worsening. Seek urgent care for severe symptoms or warning signs.' if payload.status=='worse' else 'Progress saved. Continue the instructions provided by your clinician.')
    return {'progress':progress_dict(p),'guidance':guidance,'urgent':bool(danger)}


@router.get('/doctor/api/appointments')
def doctor_appointments(request:Request,db:Session=Depends(get_db)):
    session,doctor_id=doctor_session(request,db)
    appointments=db.scalars(select(Appointment).where(Appointment.doctor_id==doctor_id,Appointment.status!='cancelled').order_by(Appointment.created_at.desc()).limit(100)).all()
    from clinic.models import User
    rows=[]
    for a in appointments:
        visit=db.scalar(select(Visit).where(Visit.appointment_id==a.id))
        t=db.get(Treatment,visit.treatment_id) if visit and visit.treatment_id else None
        rows.append({'id':a.id,'patient':db.get(User,a.user_id).name,'starts_at':a.slot.starts_at.isoformat()+'Z',
            'reason':a.reason,'status':a.status,'brief':visit.brief_snapshot if visit else 'No structured symptom check attached.',
            'can_record_treatment':bool(visit and not visit.treatment_id and a.status=='booked' and a.slot.starts_at<=utcnow()),
            'treatment':{'condition':t.condition,'summary':t.summary} if t else None,
            'progress':[progress_dict(p) for p in db.scalars(select(Progress).where(Progress.treatment_id==t.id,Progress.user_id==a.user_id).order_by(Progress.id.desc()).limit(20))] if t else []})
    return {'csrf_token':session.csrf_token,'doctor':db.get(Doctor,doctor_id).name,'appointments':rows}


class TreatmentInput(BaseModel):
    condition: str=Field(min_length=1,max_length=200)
    summary: str=Field(min_length=1,max_length=2000)
    ongoing: bool=True


@router.post('/doctor/api/appointments/{appointment_id}/treatment')
def record_treatment(appointment_id:int,payload:TreatmentInput,request:Request,db:Session=Depends(get_db)):
    session,doctor_id=doctor_session(request,db)
    check_origin(request); check_csrf(request,session)
    appointment=db.scalar(select(Appointment).where(Appointment.id==appointment_id,Appointment.doctor_id==doctor_id).with_for_update())
    if not appointment: raise HTTPException(404,'Appointment not found.')
    if appointment.status!='booked' or appointment.slot.starts_at>utcnow():
        raise HTTPException(422,'Treatment can be recorded once a booked appointment has started.')
    visit=db.scalar(select(Visit).where(Visit.appointment_id==appointment.id).with_for_update())
    if not visit: raise HTTPException(422,'Use the existing admin treatment page for appointments without a symptom check.')
    if visit.treatment_id: raise HTTPException(409,'Treatment has already been recorded for this visit.')
    if not payload.condition.strip() or not payload.summary.strip(): raise HTTPException(422,'Condition and notes are required.')
    treatment=Treatment(user_id=appointment.user_id,doctor_id=doctor_id,condition=payload.condition.strip(),summary=payload.summary.strip(),ongoing=payload.ongoing)
    db.add(treatment); db.flush()
    visit.treatment_id=treatment.id
    appointment.status='completed'
    ep=db.get(Episode,visit.episode_id); ep.status='reviewed'
    db.commit()
    return {'id':treatment.id,'status':'saved'}
