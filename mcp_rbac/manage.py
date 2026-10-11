"""Trusted operator-only CLI (never mounted as an HTTP endpoint)."""
import argparse
import asyncio
import getpass

from sqlalchemy import text

from clinic.admin_db import init_admin_tables
from clinic.database import engine, init_db
from mcp_rbac.auth import Principal
from mcp_rbac.dispatch import invoke


def main():
    parser = argparse.ArgumentParser(description='Local-only MCP operations')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create-admin', help='Create/update an admin without putting a password in shell history')
    create.add_argument('username')
    promote = sub.add_parser('promote-admin', help='Promote an existing admin by username (local machine only)')
    promote.add_argument('username')
    sub.add_parser('integrity', help='Run a restricted internal integrity check')
    sub.add_parser('cleanup', help='Run restricted internal slot cleanup')
    args = parser.parse_args()
    if args.command == 'create-admin':
        from clinic.admin_security import hash_password
        password = getpass.getpass('New admin password: ')
        again = getpass.getpass('Repeat admin password: ')
        if password != again or len(password) < 12:
            raise SystemExit('Passwords must match and be at least 12 characters.')
        init_admin_tables()
        hashed = hash_password(password)
        with engine.begin() as conn:
            row = conn.execute(text('SELECT id FROM admin_users WHERE username=:name'),
                               {'name': args.username}).first()
            if row:
                conn.execute(text('UPDATE admin_users SET password_hash=:hash, is_active=1 WHERE id=:id'),
                             {'hash': hashed, 'id': row[0]})
            else:
                conn.execute(text('INSERT INTO admin_users (username, password_hash, is_active, role) '
                                  "VALUES (:name, :hash, 1, 'admin')"),
                             {'name': args.username, 'hash': hashed})
        print('Admin account ready. Use promote-admin to grant Super Admin if necessary.')
        return
    if args.command == 'promote-admin':
        init_admin_tables()
        with engine.begin() as conn:
            row = conn.execute(text('SELECT id FROM admin_users WHERE username=:name AND is_active=1'),
                               {'name': args.username}).first()
            if not row:
                raise SystemExit('No matching active admin. Create it first with clinic.admin_setup.')
            conn.execute(text("UPDATE admin_users SET role='super_admin' WHERE id=:id"), {'id': row[0]})
        print('Super Admin role assigned. Restart existing admin session.')
        return
    init_db()
    action = 'system_integrity' if args.command == 'integrity' else 'system_cleanup'
    result = asyncio.run(invoke(Principal('system', 0), action))
    print(result)


if __name__ == '__main__':
    main()
