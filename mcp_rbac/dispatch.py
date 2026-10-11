"""Authorize every tool call independently of the LLM's requested action."""
import logging

from fastmcp import Client

from mcp_rbac.auth import AccessDenied, Principal, issue
from mcp_rbac.policy import ACTIONS, permitted

logger = logging.getLogger(__name__)

PARAMS = {
    'view_profile': frozenset(),
    'search_slots': frozenset({'specialty', 'doctor_name', 'limit'}),
    'book_slot': frozenset({'slot_id', 'reason'}),
    'my_appointments': frozenset(),
    'cancel_appointment': frozenset({'appointment_id'}),
    'admin_doctors': frozenset({'search'}),
    'admin_add_slot': frozenset({'doctor_id', 'starts_at', 'minutes'}),
    'admin_appointments': frozenset({'limit'}),
    'admin_set_status': frozenset({'appointment_id', 'status'}),
    'admin_stats': frozenset(),
    'admin_audit': frozenset({'limit'}),
    'admin_set_role': frozenset({'admin_id', 'role'}),
    'system_integrity': frozenset(),
    'system_cleanup': frozenset(),
}


async def invoke(principal: Principal, action: str, params: dict | None = None) -> dict:
    """Only this dispatcher is called by the HTTP API; capabilities stay private."""
    if not permitted(principal.role, action):
        raise AccessDenied('You do not have permission for this action.')
    params = params or {}
    if not isinstance(params, dict) or set(params) - PARAMS[action]:
        raise ValueError('Unsupported parameter. Raw SQL and user_id override are not accepted.')
    token = issue(principal, action)
    # Imported lazily so tooling can inspect RBAC without loading the MCP runtime.
    from mcp_rbac.servers import SERVERS
    async with Client(SERVERS[ACTIONS[action].server]) as client:
        result = await client.call_tool(action, {'capability': token, **params})
    if getattr(result, 'is_error', False) or getattr(result, 'isError', False):
        logger.warning('MCP tool failed: %s', action)
        raise ValueError('Tool could not complete the requested operation.')
    data = getattr(result, 'data', None)
    if not isinstance(data, dict):
        raise RuntimeError('MCP tool returned an invalid response.')
    if data.get('status') not in ('OK', 'NO'):
        raise RuntimeError('MCP tool returned an unknown status.')
    return {'action': action, **data}
