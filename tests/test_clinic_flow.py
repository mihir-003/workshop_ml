"""Integration checks with a temporary SQLite database and a fake Groq response."""
import os
import tempfile
import unittest
from io import BytesIO
from datetime import timedelta
from unittest.mock import patch

_dbfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_dbfile.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _dbfile.name

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from clinic.database import SessionLocal  # noqa: E402
from clinic.models import Appointment, Doctor, Slot, Treatment, User, utcnow  # noqa: E402
from main import app  # noqa: E402


class ClinicFlow(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        os.unlink(_dbfile.name)

    def test_history_booking_collision_and_logout(self):
        with TestClient(app) as first, TestClient(app) as second:
            self.assertEqual(first.post("/signup", data={"name": "Mohit", "email": "mohit@example.com", "password": "safe-password-123"}).status_code, 200)
            self.assertEqual(second.post("/signup", data={"name": "Other", "email": "other@example.com", "password": "safe-password-456"}).status_code, 200)
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.email == "mohit@example.com"))
                doctor = Doctor(name="Ravi Mehta", specialty="Gastroenterology")
                db.add(doctor); db.flush()
                slot = Slot(doctor_id=doctor.id, starts_at=utcnow() + timedelta(days=2), ends_at=utcnow() + timedelta(days=2, minutes=30))
                db.add(slot)
                db.add(Treatment(user_id=user.id, doctor_id=doctor.id, condition="stomach ulcer", summary="Follow-up planned", ongoing=True))
                db.commit()
                slot_id = slot.id
            csrf1 = first.get("/api/me").json()["csrf_token"]
            csrf2 = second.get("/api/me").json()["csrf_token"]
            result = first.post("/api/chat", json={"message":"hi"}, headers={"X-CSRF-Token":csrf1})
            self.assertIn("Dr. Ravi Mehta", result.json()["reply"])
            self.assertEqual(result.json()["slots"][0]["slot_id"], slot_id)
            self.assertEqual(second.post("/api/bookings", json={"slot_id":slot_id}, headers={"X-CSRF-Token":csrf1}).status_code, 403)
            booking = first.post("/api/bookings", json={"slot_id":slot_id}, headers={"X-CSRF-Token":csrf1})
            self.assertEqual(booking.status_code, 200)
            self.assertEqual(second.post("/api/bookings", json={"slot_id":slot_id}, headers={"X-CSRF-Token":csrf2}).status_code, 409)
            appointment_id = booking.json()["id"]
            self.assertEqual(first.post(f"/api/bookings/{appointment_id}/cancel", headers={"X-CSRF-Token":csrf1}).status_code, 200)
            self.assertEqual(second.post("/api/bookings", json={"slot_id":slot_id}, headers={"X-CSRF-Token":csrf2}).status_code, 200)
            self.assertEqual(first.post("/logout", headers={"X-CSRF-Token":csrf1}).status_code, 200)
            self.assertEqual(first.get("/api/me").json(), {"authenticated":False})

    def test_urgent_symptom_suppresses_slots(self):
        with TestClient(app) as client:
            client.post("/signup", data={"name":"Urgent User", "email":"urgent@example.com", "password":"safe-password-789"})
            csrf = client.get("/api/me").json()["csrf_token"]
            result = client.post("/api/chat", json={"message":"I have chest pain and trouble breathing"}, headers={"X-CSRF-Token":csrf})
            self.assertTrue(result.json()["urgent"])
            self.assertEqual(result.json()["slots"], [])

    def test_groq_routing_and_photo_consent(self):
        with TestClient(app) as client:
            client.post("/signup", data={"name":"New Patient", "email":"new@example.com", "password":"safe-password-new"})
            csrf = client.get("/api/me").json()["csrf_token"]
            headers = {"X-CSRF-Token":csrf}
            with SessionLocal() as db:
                doctor = Doctor(name="Nila", specialty="Neurology")
                db.add(doctor); db.flush()
                db.add(Slot(doctor_id=doctor.id, starts_at=utcnow()+timedelta(days=3), ends_at=utcnow()+timedelta(days=3, minutes=30)))
                db.commit()
            with patch("clinic.assistant.ask_groq", return_value={"advice":"Please consult a clinician about your symptoms.","specialty":"General Medicine","urgent":False}):
                first = client.post("/api/chat", json={"message":"When is a neurologist available?"}, headers=headers).json()
                self.assertEqual(first["specialty"], "Neurology")
                self.assertTrue(first["slots"])
                again = client.post("/api/chat", json={"message":"Which doctor is available?"}, headers=headers).json()
                self.assertEqual(again["specialty"], "Neurology")
                self.assertEqual(again["slots"][0]["doctor"], "Nila")
                image = BytesIO(); Image.new("RGB", (4,4), "red").save(image, format="PNG")
                file = {"image": ("wound.png", image.getvalue(), "image/png")}
                self.assertEqual(client.post("/api/chat/photo", files=file, headers=headers).status_code, 400)
                result = client.post("/api/chat/photo", files=file, data={"consent":"true", "message":"Small scratch"}, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertIn("photo cannot establish injury severity", result.json()["reply"])


if __name__ == "__main__":
    unittest.main()
