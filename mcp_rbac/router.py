"""Authenticated browser -> FastAPI -> private FastMCP client -> scoped tool."""
import hmac
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from clinic.admin_security import COOKIE_NAME, read_session_token
from clinic.database import engine, get_db
from clinic.security import check_csrf, check_origin, current_session
from mcp_rbac.audit import record
from mcp_rbac.auth import AccessDenied, Principal, csrf_for_admin_cookie, valid_admin_csrf
from mcp_rbac.dispatch import invoke
from mcp_rbac.conversation import respond
from mcp_rbac.policy import allowed_actions, permitted

logger = logging.getLogger(__name__)
router = APIRouter(tags=['Secure MCP Assistant'])
templates = Jinja2Templates(directory='templates')


class ExecuteRequest(BaseModel):
    action: str = Field(min_length=1, max_length=60)
    params: dict = Field(default_factory=dict)


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(default=None, max_length=100)


def _admin_login(request: Request):
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    # This security-sensitive feature must never use the admin module's dev default.
    secret = os.getenv('ADMIN_SESSION_SECRET', '')
    if len(secret) < 32 or secret == 'dev-only-change-this-secret':
        raise HTTPException(503, 'Configure a strong ADMIN_SESSION_SECRET first.')
    payload = read_session_token(cookie)
    if not payload:
        return None
    from clinic.admin_db import init_admin_tables
    init_admin_tables()
    with engine.connect() as conn:
        row = conn.execute(text('SELECT id, username, role, is_active FROM admin_users WHERE id=:id'),
                           {'id': payload['admin_id']}).mappings().first()
    if (not row or not row['is_active'] or row['username'] != payload.get('username')
            or row['role'] not in ('admin', 'super_admin')):
        return None
    return Principal(row['role'], int(row['id'])), csrf_for_admin_cookie(cookie)


def _identity(request: Request, db: Session):
    admin = _admin_login(request)
    if admin:
        return admin
    session = current_session(request, db)
    if session:
        return Principal('user', session.user_id), session.csrf_token
    raise HTTPException(401, 'Log in as a patient or administrator first.')


def _authorize_post(request: Request, db: Session):
    principal, token = _identity(request, db)
    check_origin(request)
    supplied = request.headers.get('X-CSRF-Token', '')
    if not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(403, 'Invalid CSRF token.')
    return principal


@router.get('/newpage.html', response_class=HTMLResponse)
def mcp_page(request: Request):
    return templates.TemplateResponse(request=request, name='newpage.html')


@router.get('/api/mcp/session')
def session(request: Request, db: Session = Depends(get_db)):
    try:
        principal, csrf_token = _identity(request, db)
    except HTTPException as exc:
        if exc.status_code == 401:
            return {'authenticated': False, 'login_url': '/login', 'admin_login_url': '/admin/login'}
        raise
    return {'authenticated': True, 'role': principal.role, 'csrf_token': csrf_token,
            'actions': allowed_actions(principal.role)}


@router.post('/api/mcp/execute')
async def execute(body: ExecuteRequest, request: Request, db: Session = Depends(get_db)):
    actor = _authorize_post(request, db)
    if not permitted(actor.role, body.action) or actor.role == 'system':
        record(actor.role, actor.subject_id, body.action, 'denied')
        raise HTTPException(403, 'Permission denied.')
    # Restrict size and caller-controlled fields before FastMCP sees them.
    if len(json.dumps(body.params, default=str)) > 4000:
        raise HTTPException(422, 'Parameters are too large.')
    try:
        data = await invoke(actor, body.action, body.params)
    except AccessDenied:
        record(actor.role, actor.subject_id, body.action, 'denied')
        raise HTTPException(403, 'Permission denied.')
    except ValueError as exc:
        record(actor.role, actor.subject_id, body.action, 'invalid')
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        record(actor.role, actor.subject_id, body.action, 'error')
        logger.exception('MCP execution failed for %s', body.action)
        raise HTTPException(503, 'Database or MCP service unavailable; no verified answer.') from exc
    record(actor.role, actor.subject_id, body.action, data['status'].lower())
    return data


@router.post('/api/mcp/message')
async def message(body: MessageRequest, request: Request, db: Session = Depends(get_db)):
    """Single chat entrypoint: only server-selected MCP actions, never tool forms."""
    actor = _authorize_post(request, db)
    # Same login/CSRF boundary as /api/mcp/execute; chat state never grants
    # permissions or transfers across users, roles or browser login sessions.
    _, credential = _identity(request, db)
    try:
        return await respond(actor, credential, body.message, body.conversation_id)
    except AccessDenied:
        record(actor.role, actor.subject_id, 'chat', 'denied')
        raise HTTPException(403, 'Permission denied.')
    except ValueError as exc:
        record(actor.role, actor.subject_id, 'chat', 'invalid')
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        record(actor.role, actor.subject_id, 'chat', 'error')
        logger.exception('MCP conversational assistant failed')
        raise HTTPException(503, 'Database or MCP service unavailable; no verified answer.') from exc
