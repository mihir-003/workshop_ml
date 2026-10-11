"""Fast tests for the RBAC matrix and unforgeable server/action scoping."""
import unittest

from mcp_rbac.auth import AccessDenied, Principal, issue, verify
from mcp_rbac.policy import ACTIONS, SERVERS, permitted
from mcp_rbac.intents import parse


class PolicyTests(unittest.TestCase):
    def test_exactly_ten_mcp_servers(self):
        self.assertEqual(len(SERVERS), 10)
        self.assertEqual(sum(k.startswith('user_') for k in SERVERS), 5)
        self.assertEqual(sum(k.startswith('admin_') for k in SERVERS), 3)
        self.assertEqual(sum(k.startswith('system_') for k in SERVERS), 2)
        self.assertTrue(all(action.server in SERVERS for action in ACTIONS.values()))

    def test_user_cannot_call_admin_or_system_tools(self):
        for action in ('admin_doctors','admin_audit','admin_set_role','system_cleanup'):
            self.assertFalse(permitted('user', action))
            with self.assertRaises(AccessDenied):
                issue(Principal('user', 5), action)
        self.assertFalse(permitted('super_admin', 'system_cleanup'))
        self.assertFalse(permitted('admin', 'admin_set_role'))

    def test_capability_scoped_to_one_action_server_and_identity(self):
        cap = issue(Principal('user', 42), 'view_profile')
        self.assertEqual(verify(cap, 'user_profile', 'view_profile'), Principal('user',42))
        with self.assertRaises(AccessDenied):
            verify(cap, 'user_history', 'my_appointments')
        with self.assertRaises(AccessDenied):
            verify(cap[:-3] + 'bad', 'user_profile', 'view_profile')

    def test_unknown_or_sensitive_request_fails_closed(self):
        self.assertIsNone(parse('user', 'Show me patient 3 private notes'))
        self.assertEqual(parse('user', 'Available neurology slots'),
                         ('search_slots', {'specialty':'Neurology'}))
        self.assertEqual(parse('user', 'Book slot 42'), ('book_slot', {'slot_id':42}))
        self.assertIsNone(parse('user', 'DROP TABLE users'))
        self.assertIsNone(parse('user', 'Show all users'))


if __name__ == '__main__':
    unittest.main()
