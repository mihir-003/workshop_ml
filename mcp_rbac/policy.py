"""A central, explicit RBAC catalogue shared by the API and the MCP servers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    server: str
    roles: frozenset[str]
    description: str


# Exactly ten independently instantiated FastMCP servers (5/3/2).
SERVERS = {
    'user_profile': 'User / Profile',
    'user_availability': 'User / Availability',
    'user_booking': 'User / Booking',
    'user_history': 'User / History',
    'user_cancellation': 'User / Cancellation',
    'admin_resources': 'Admin / Resources',
    'admin_appointments': 'Admin / Appointments',
    'admin_reporting': 'Admin / Reporting and Roles',
    'system_policy': 'System / Integrity',
    'system_maintenance': 'System / Maintenance',
}
USER = frozenset({'user'})
ADMIN = frozenset({'admin', 'super_admin'})
SUPER = frozenset({'super_admin'})
SYSTEM = frozenset({'system'})

ACTIONS: dict[str, Action] = {
    'view_profile': Action('user_profile', USER, 'View your own profile'),
    'search_slots': Action('user_availability', USER, 'Find actual future free slots'),
    'book_slot': Action('user_booking', USER, 'Book one real available slot'),
    'my_appointments': Action('user_history', USER, 'List your own appointments'),
    'cancel_appointment': Action('user_cancellation', USER, 'Cancel your own future appointment'),
    'admin_doctors': Action('admin_resources', ADMIN, 'View doctors and their specialties'),
    'admin_add_slot': Action('admin_resources', ADMIN, 'Add a validated doctor availability slot'),
    'admin_appointments': Action('admin_appointments', ADMIN, 'List appointments'),
    'admin_set_status': Action('admin_appointments', ADMIN, 'Update an appointment status'),
    'admin_stats': Action('admin_reporting', ADMIN, 'View aggregate clinic totals'),
    'admin_audit': Action('admin_reporting', SUPER, 'Review sanitized MCP audit events'),
    'admin_set_role': Action('admin_reporting', SUPER, 'Change an admin account role'),
    'system_integrity': Action('system_policy', SYSTEM, 'Verify appointment slot consistency'),
    'system_cleanup': Action('system_maintenance', SYSTEM, 'Expire unused past appointment slots'),
}


def permitted(role: str, action: str) -> bool:
    return action in ACTIONS and role in ACTIONS[action].roles


def allowed_actions(role: str):
    return [{'name': name, 'server': spec.server, 'description': spec.description}
            for name, spec in ACTIONS.items() if role in spec.roles]
