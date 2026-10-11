"""Short-lived, HMAC-authenticated capabilities; no credentials reach the model or browser.

The secret is process-local, and FastMCP servers use in-process transport only.
No public MCP listener exists: a remote caller cannot create a capability.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from mcp_rbac.policy import ACTIONS, permitted

_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class Principal:
    role: str
    subject_id: int


class AccessDenied(PermissionError):
    pass


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def issue(principal: Principal, action: str) -> str:
    """Called ONLY by the authenticated FastAPI dispatcher or trusted maintenance CLI."""
    if not permitted(principal.role, action):
        raise AccessDenied('This role cannot use that tool.')
    body = {'role': principal.role, 'sub': principal.subject_id, 'action': action,
            'server': ACTIONS[action].server, 'exp': int(time.time()) + 30,
            'nonce': secrets.token_hex(12)}
    payload = _encode(json.dumps(body, separators=(',', ':'), sort_keys=True).encode())
    sig = hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}.{sig}'


def verify(capability: str, server: str, action: str) -> Principal:
    try:
        payload, sig = capability.split('.', 1)
        expected = hmac.new(_KEY, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise AccessDenied('Invalid capability.')
        raw = base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))
        data = json.loads(raw)
        if (data['exp'] < int(time.time()) or data['exp'] > int(time.time()) + 30
                or data['server'] != server or data['action'] != action):
            raise AccessDenied('Capability expired or scoped to another tool.')
        principal = Principal(role=data['role'], subject_id=int(data['sub']))
        if principal.subject_id < 0 or not permitted(principal.role, action):
            raise AccessDenied('Access denied.')
        return principal
    except AccessDenied:
        raise
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccessDenied('Invalid capability.') from exc


def csrf_for_admin_cookie(cookie: str) -> str:
    return hmac.new(_KEY, ('admin-csrf:' + cookie).encode(), hashlib.sha256).hexdigest()


def valid_admin_csrf(cookie: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(csrf_for_admin_cookie(cookie), token)
