"""Administrative CLI: provision staff accounts and agent profiles.

    python -m kural.cli create-user --username ops1 --role OPS_MANAGER --email ops1@bank.in --full-name "Ops One"
    python -m kural.cli create-user ... --agent --skills APP_SUPPORT,GENERAL_SUPPORT --languages English,Hindi

The password is read from KURAL_NEW_USER_PASSWORD or prompted; there is no default password.
"""

import argparse
import getpass
import os
import sys

from kural.config import get_settings
from kural.persistence.database import Database
from kural.security.rbac import ALL_ROLES
from kural.services.agent_service import AgentService
from kural.services.auth_service import AuthService


def main() -> None:
    parser = argparse.ArgumentParser(description="KURAL AVA administrative CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-user", "init-admin"):
        p = sub.add_parser(name, help="Provision a staff account")
        p.add_argument("--username", required=True)
        p.add_argument("--email", required=True)
        p.add_argument("--full-name", required=True)
        p.add_argument("--role", default="SYSTEM_ADMIN" if name == "init-admin" else None, required=name != "init-admin",
                       choices=sorted(ALL_ROLES))
        p.add_argument("--branch", default="Head Office")
        p.add_argument("--phone", default=None, help="Mobile for SMS notifications (optional)")
        p.add_argument("--agent", action="store_true", help="Also create a linked human-agent profile")
        p.add_argument("--skills", default="GENERAL_SUPPORT,APP_SUPPORT")
        p.add_argument("--languages", default="English")
    args = parser.parse_args()

    password = os.environ.get("KURAL_NEW_USER_PASSWORD") or getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters.")
    db = Database()
    db.prepare_schema(auto_migrate=get_settings().auto_migrate)
    user = AuthService(db).provision_user(
        username=args.username, email=args.email, password=password, full_name=args.full_name,
        role=args.role, branch=args.branch, phone=args.phone,
    )
    print(f"Created user {user['username']} ({user['role']}) id={user['id']}")
    if args.agent:
        agent = AgentService(db).create_agent(
            name=args.full_name, skills=args.skills.split(","), languages=args.languages.split(","),
            availability="OFFLINE", user_id=user["id"], phone=args.phone, email=args.email,
        )
        print(f"Created agent profile {agent['id']} linked to {user['username']}")


if __name__ == "__main__":
    main()
