import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from clinic.models import LoginSession, utcnow

COOKIE = "clinic_session"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, cost, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        computed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(cost), r=8, p=1)
        return hmac.compare_digest(computed, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_session(request: Request, db: Session):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(token), LoginSession.expires_at > utcnow()))


def require_session(request: Request, db: Session):
    session = current_session(request, db)
    if session is None:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    return session


def check_csrf(request: Request, session: LoginSession):
    submitted = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(submitted, session.csrf_token):
        raise HTTPException(status_code=403, detail="Invalid security token. Reload the page.")


def check_origin(request: Request):
    # Browser POSTs must originate from this site. URL fragments and query strings are ignored.
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Invalid request origin.")


def create_session(db: Session, user_id: int):
    token = secrets.token_urlsafe(32)
    session = LoginSession(user_id=user_id, token_hash=token_hash(token), csrf_token=secrets.token_urlsafe(32), expires_at=utcnow() + timedelta(days=7))
    db.add(session)
    db.commit()
    return token


def set_auth_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=7 * 86400, httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", path="/")
