import argparse

from sqlalchemy import text

from clinic.admin_db import init_admin_tables
from clinic.admin_security import hash_password
from clinic.database import engine


def create_admin(username: str, password: str) -> None:
    init_admin_tables()
    password_hash = hash_password(password)
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM admin_users WHERE username=:username"),
            {"username": username},
        ).first()
        if existing:
            conn.execute(
                text("UPDATE admin_users SET password_hash=:password_hash, is_active=1 WHERE username=:username"),
                {"username": username, "password_hash": password_hash},
            )
            print(f"Admin '{username}' password updated.")
        else:
            conn.execute(
                text("INSERT INTO admin_users (username, password_hash, is_active) VALUES (:username, :password_hash, 1)"),
                {"username": username, "password_hash": password_hash},
            )
            print(f"Admin '{username}' created.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset a Sanjeevani admin account")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("username")
    create.add_argument("password")
    args = parser.parse_args()
    if args.command == "create":
        create_admin(args.username, args.password)


if __name__ == "__main__":
    main()
