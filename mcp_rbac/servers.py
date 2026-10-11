"""Ten private FastMCP servers, split 5 patient / 3 admin / 2 internal system.

They are used through FastMCP's in-memory Client(server) transport.
They MUST NOT be published via mcp.run(host='0.0.0.0') without a
separate authenticated gateway, because the capability issuer is in-process.
"""
from fastmcp import FastMCP

from mcp_rbac.auth import verify
from mcp_rbac.policy import SERVERS as SERVER_NAMES
from mcp_rbac import services

SERVERS = {name: FastMCP(display) for name, display in SERVER_NAMES.items()}


def checked(capability: str, server: str, action: str):
    return verify(capability, server, action)


# 1 / USER: PROFILE
@SERVERS['user_profile'].tool()
def view_profile(capability: str) -> dict:
    """Retrieve the logged-in account's own identity only."""
    return services.profile(checked(capability, 'user_profile', 'view_profile'))


# 2 / USER: AVAILABILITY
@SERVERS['user_availability'].tool()
def search_slots(capability: str, specialty: str = '', doctor_name: str = '', limit: int = 10) -> dict:
    """Search verified unbooked future slots in MySQL, never invented availability."""
    return services.slots(checked(capability, 'user_availability', 'search_slots'),
                          specialty, doctor_name, limit)


# 3 / USER: BOOKINGS
@SERVERS['user_booking'].tool()
def book_slot(capability: str, slot_id: int, reason: str = 'Consultation') -> dict:
    """Book an existing slot for the authenticated patient. No user_id argument."""
    return services.book(checked(capability, 'user_booking', 'book_slot'), slot_id, reason)


# 4 / USER: HISTORY
@SERVERS['user_history'].tool()
def my_appointments(capability: str) -> dict:
    """Read only appointments owned by the authenticated patient."""
    return services.appointments(checked(capability, 'user_history', 'my_appointments'))


# 5 / USER: CANCELLATIONS
@SERVERS['user_cancellation'].tool()
def cancel_appointment(capability: str, appointment_id: int) -> dict:
    """Cancel an eligible appointment belonging to the authenticated patient."""
    return services.cancel(checked(capability, 'user_cancellation', 'cancel_appointment'), appointment_id)


# 6 / ADMIN: RESOURCES
@SERVERS['admin_resources'].tool()
def admin_doctors(capability: str, search: str = '') -> dict:
    """Display doctors and specialties with no private patient information."""
    return services.admin_doctors(checked(capability, 'admin_resources', 'admin_doctors'), search)


@SERVERS['admin_resources'].tool()
def admin_add_slot(capability: str, doctor_id: int, starts_at: str, minutes: int = 30) -> dict:
    """Add a conflict-checked slot for a real active doctor."""
    return services.admin_add_slot(checked(capability, 'admin_resources', 'admin_add_slot'),
                                   doctor_id, starts_at, minutes)


# 7 / ADMIN: APPOINTMENT MANAGEMENT
@SERVERS['admin_appointments'].tool()
def admin_appointments(capability: str, limit: int = 20) -> dict:
    """Show current clinic appointments, restricted to signed-in admin staff."""
    return services.admin_appointments(checked(capability, 'admin_appointments', 'admin_appointments'), limit)


@SERVERS['admin_appointments'].tool()
def admin_set_status(capability: str, appointment_id: int, status: str) -> dict:
    """Change booking state according to the clinic's existing slot rules."""
    return services.admin_set_status(checked(capability, 'admin_appointments', 'admin_set_status'),
                                     appointment_id, status)


# 8 / ADMIN: REPORTING, AUDIT, SUPERADMIN ROLE ASSIGNMENT
@SERVERS['admin_reporting'].tool()
def admin_stats(capability: str) -> dict:
    """Return real aggregate counts from the clinic DB."""
    return services.admin_stats(checked(capability, 'admin_reporting', 'admin_stats'))


@SERVERS['admin_reporting'].tool()
def admin_audit(capability: str, limit: int = 20) -> dict:
    """Super Admin only: sanitized audit events without chat text or secrets."""
    return services.admin_audit(checked(capability, 'admin_reporting', 'admin_audit'), limit)


@SERVERS['admin_reporting'].tool()
def admin_set_role(capability: str, admin_id: int, role: str) -> dict:
    """Super Admin only: grant or revoke an admin account's Super Admin role."""
    return services.admin_set_role(checked(capability, 'admin_reporting', 'admin_set_role'),
                                   admin_id, role)


# 9 / SYSTEM: INTEGRITY (not available via HTTP)
@SERVERS['system_policy'].tool()
def system_integrity(capability: str) -> dict:
    """Internal service only: inspect booking/slot consistency."""
    return services.system_integrity(checked(capability, 'system_policy', 'system_integrity'))


# 10 / SYSTEM: MAINTENANCE (not available via HTTP)
@SERVERS['system_maintenance'].tool()
def system_cleanup(capability: str) -> dict:
    """Internal service only: expire unused historical slots."""
    return services.system_cleanup(checked(capability, 'system_maintenance', 'system_cleanup'))
