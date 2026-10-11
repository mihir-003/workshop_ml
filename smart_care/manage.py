"""Trusted local command: link an existing patient login to a real doctor record."""
import argparse
from sqlalchemy import select
from clinic.database import SessionLocal, init_db
from clinic.models import User, Doctor
from smart_care.models import DoctorAccess, Episode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['grant-doctor','revoke-doctor','review-urgent'])
    parser.add_argument('email',help='Existing account email')
    parser.add_argument('doctor_id',type=int,nargs='?',help='Doctor ID, or episode ID for review-urgent')
    parser.add_argument('--note',default='',help='Clinician review note; required for review-urgent')
    args=parser.parse_args()
    init_db()
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==args.email.strip().lower()))
        if not user: parser.error('Register the doctor account through /signup first.')
        access=db.scalar(select(DoctorAccess).where(DoctorAccess.user_id==user.id))
        if args.action=='review-urgent':
            ep=db.scalar(select(Episode).where(Episode.id==args.doctor_id,Episode.user_id==user.id,Episode.status=='urgent'))
            if not ep or not args.note.strip(): parser.error('Provide an unresolved urgent episode ID and --note describing the in-person clinician review.')
            ep.status='reviewed'
            ep.transcript=list(ep.transcript)+[{'role':'clinic','text':args.note.strip()[:2000]}]
        elif args.action=='revoke-doctor':
            if access: db.delete(access)
        else:
            doctor=db.get(Doctor,args.doctor_id) if args.doctor_id else None
            if not doctor or not doctor.active: parser.error('Supply an active doctor ID from your admin dashboard.')
            if access: access.doctor_id=doctor.id
            else: db.add(DoctorAccess(user_id=user.id,doctor_id=doctor.id))
        db.commit()
    print('Trusted clinic update saved.')

if __name__=='__main__': main()
