"""Command-line administrative utilities for KURAL AVA."""

import argparse
import sys
from kural.persistence.database import Database
from kural.services.auth_service import AuthService


def main():
    parser = argparse.ArgumentParser(description="KURAL AVA Administrative CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_parser = subparsers.add_parser("init-admin", help="Provision initial system administrator")
    admin_parser.add_argument("--username", default="admin", help="Admin username")
    admin_parser.add_argument("--email", default="admin@townbank.internal", help="Admin email")
    admin_parser.add_argument("--password", default="AdminSecret2026!", help="Admin password")
    admin_parser.add_argument("--full-name", default="System Administrator", help="Admin full name")
    admin_parser.add_argument("--role", default="SYSTEM_ADMIN", help="Role (default: SYSTEM_ADMIN)")
    admin_parser.add_argument("--branch", default="Headquarters", help="Branch (default: Headquarters)")

    args = parser.parse_args()

    if args.command == "init-admin":
        db = Database()
        db.create_tables()
        auth_svc = AuthService(db)
        try:
            user = auth_svc.provision_user(
                username=args.username,
                email=args.email,
                password=args.password,
                full_name=args.full_name,
                role=args.role,
                branch=args.branch,
            )
            print(f"Administrator successfully initialized: {user['username']} ({user['role']})")
        except Exception as e:
            print(f"Admin initialization notice: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
