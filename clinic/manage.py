"""Clinic operator commands. Run only on the trusted clinic server.

Examples:
  python -m clinic.manage add-doctor "Asha Sharma" Neurology
  python -m clinic.manage add-slot 1 "2026-10-01T10:00:00+05:30" 30
  python -m clinic.manage add-treatment patient@example.com 1 "stomach ulcer" "Follow-up planned" --ongoing
"""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from clinic.assistant import SPECIALTIES
from clinic.database import SessionLocal, init_db
from clinic.models import Doctor, Slot, Treatment, User, utcnow


def main():
    parser = argparse.ArgumentParser(description="Trusted clinic operator commands (do not expose as web routes)")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("add-doctor")
    doctor.add_argument("name")
    doctor.add_argument("specialty", choices=SPECIALTIES)
    slot = sub.add_parser("add-slot")
    slot.add_argument("doctor_id", type=int)
    slot.add_argument("starts_at", help="ISO time including timezone, e.g. 2026-10-01T10:00:00+05:30")
    slot.add_argument("minutes", type=int)
    treatment = sub.add_parser("add-treatment")
    treatment.add_argument("patient_email")
    treatment.add_argument("doctor_id", type=int)
    treatment.add_argument("condition")
    treatment.add_argument("summary")
    treatment.add_argument("--ongoing", action="store_true")
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        if args.command == "add-doctor":
            record = Doctor(name=args.name.strip(), specialty=args.specialty)
        elif args.command == "add-slot":
            doctor = db.get(Doctor, args.doctor_id)
            if not doctor or not doctor.active or not (5 <= args.minutes <= 240):
                parser.error("Active doctor and a duration of 5–240 minutes required")
            time = datetime.fromisoformat(args.starts_at)
            if time.tzinfo is None:
                parser.error("Include the timezone offset in starts_at")
            start = time.astimezone(timezone.utc).replace(tzinfo=None)
            if start <= utcnow():
                parser.error("Slot must be in the future")
            end = start + timedelta(minutes=args.minutes)
            for existing in db.scalars(select(Slot).where(Slot.doctor_id == doctor.id, Slot.starts_at < end, Slot.ends_at > start)):
                parser.error(f"Overlaps slot {existing.id}")
            record = Slot(doctor_id=doctor.id, starts_at=start, ends_at=end)
        else:
            patient = db.scalar(select(User).where(User.email == args.patient_email.lower()))
            doctor = db.get(Doctor, args.doctor_id)
            if not patient or not doctor or not args.condition.strip():
                parser.error("Existing patient, doctor and a condition required")
            record = Treatment(user_id=patient.id, doctor_id=doctor.id, condition=args.condition[:200], summary=args.summary[:2000], ongoing=args.ongoing)
        db.add(record)
        db.commit()
        print(f"{args.command}: id={record.id}")


if __name__ == "__main__":
    main()
