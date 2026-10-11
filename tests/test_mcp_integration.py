"""Real FastMCP + FastAPI integration tests with a temporary SQLite database.

Run separately: uv run python -m unittest tests/test_mcp_integration.py
No MySQL, Groq key, or internet required (FastMCP must already be installed).
"""
import os
import tempfile
import unittest
from datetime import timedelta

import importlib.util

if importlib.util.find_spec('fastmcp') is None:
    raise unittest.SkipTest('FastMCP is not installed in this environment')

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_db.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _db.name
os.environ['ADMIN_SESSION_SECRET'] = 'test-only-' + 'a' * 48

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from clinic import models  # noqa: E402
from clinic.database import SessionLocal, engine, init_db  # noqa: E402
from clinic.models import Appointment, Doctor, Slot, User, utcnow  # noqa: E402
from clinic.security import COOKIE, create_session, hash_password  # noqa: E402
from clinic.admin_security import COOKIE_NAME, create_session_token  # noqa: E402
from mcp_rbac.router import router  # noqa: E402


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        # The real admin schema is MySQL-specific; make the minimal SQLite
        # role table and stub only its MySQL DDL initializer in these tests.
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, is_active BOOLEAN)'))
            conn.execute(text("INSERT INTO admin_users VALUES (1, 'admin1', 'admin', 1), (2, 'rootadmin', 'super_admin', 1)"))
        import clinic.admin_db as admin_db
        cls._old_init = admin_db.init_admin_tables
        admin_db.init_admin_tables = lambda: None
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)
        with SessionLocal() as db:
            for id_, name in ((1, 'User One'), (2, 'User Two')):
                db.add(User(id=id_, name=name, email=f'test{id_}@example.com',
                            password_hash=hash_password('password-123456')))
            db.add(Doctor(id=1, name='Verified Neurologist', specialty='Neurology', active=True))
            db.add(Slot(id=100, doctor_id=1, starts_at=utcnow()+timedelta(days=2),
                        ends_at=utcnow()+timedelta(days=2,minutes=30), booked=False))
            db.commit()
            cls.cookies = {}
            for user in (1, 2):
                token = create_session(db, user)
                cls.cookies[user] = {COOKIE: token}

    @classmethod
    def tearDownClass(cls):
        import clinic.admin_db as admin_db
        admin_db.init_admin_tables = cls._old_init
        cls.client.close()
        engine.dispose()
        os.unlink(_db.name)

    def headers(self, cookies):
        val = self.client.get('/api/mcp/session', cookies=cookies)
        self.assertEqual(val.status_code, 200)
        return {'X-CSRF-Token': val.json()['csrf_token']}

    def request(self, cookies, action, params=None, token=True):
        headers = self.headers(cookies) if token else {}
        return self.client.post('/api/mcp/execute', cookies=cookies,
                 json={'action':action,'params':params or {}}, headers=headers)

    def test_patients_can_only_access_their_own_records(self):
        a, b = self.cookies[1], self.cookies[2]
        self.assertEqual(self.request(a, 'view_profile').json()['data']['id'], 1)
        self.assertEqual(self.request(b, 'view_profile').json()['data']['id'], 2)
        self.assertEqual(self.request(a, 'search_slots', {'specialty':'Neurology'}).json()['status'], 'OK')
        book = self.request(a, 'book_slot', {'slot_id':100})
        self.assertEqual(book.status_code, 200, book.text)
        appointment_id = book.json()['data']['id']
        self.assertEqual(self.request(b, 'cancel_appointment', {'appointment_id':appointment_id}).json()['status'], 'NO')
        self.assertEqual(self.request(b, 'my_appointments').json()['status'], 'NO')
        self.assertEqual(self.request(a, 'cancel_appointment', {'appointment_id':appointment_id}).json()['status'], 'OK')
        self.assertEqual(self.request(a, 'cancel_appointment', {'appointment_id':99999}).json()['status'], 'NO')

    def test_protects_user_requests_and_parameters(self):
        a = self.cookies[1]
        self.assertEqual(self.request(a, 'admin_stats').status_code, 403)
        self.assertEqual(self.request(a, 'system_cleanup').status_code, 403)
        self.assertEqual(self.request(a, 'view_profile', {'user_id':2}).status_code, 422)
        self.assertEqual(self.request(a, 'view_profile', token=False).status_code, 403)
        self.assertEqual(self.client.post('/api/mcp/execute', json={'action':'view_profile'}).status_code, 401)
        ans = self.client.post('/api/mcp/message', cookies=a, headers=self.headers(a),
                               json={'message':'Patient #2 secret history'}).json()
        self.assertEqual(ans['status'], 'NO')

    def test_admin_super_admin_and_revocation(self):
        admin = {COOKIE_NAME: create_session_token(1, 'admin1')}
        superadmin = {COOKIE_NAME: create_session_token(2, 'rootadmin')}
        self.assertEqual(self.request(admin, 'admin_stats').status_code, 200)
        self.assertEqual(self.request(admin, 'admin_audit').status_code, 403)
        self.assertEqual(self.request(superadmin, 'admin_audit').status_code, 200)
        self.assertEqual(self.request(superadmin, 'system_integrity').status_code, 403)
        with engine.begin() as conn:
            conn.execute(text('UPDATE admin_users SET is_active=0 WHERE id=1'))
        self.assertEqual(self.client.post('/api/mcp/execute', cookies=admin,
            json={'action':'admin_stats','params':{}},
            headers={'X-CSRF-Token':'irrelevant'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
