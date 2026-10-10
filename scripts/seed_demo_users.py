"""Seed the 6 standard bank presentation personas with realistic profiles, credentials and activity."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from kural.persistence.database import Database
from kural.persistence.models import AgentRow, OperationsAuditEventRow, UserRow
from kural.security.crypto import hash_password

DEMO_USERS = [
    {
        "username": "admin",
        "email": "admin@kural.bank",
        "password": "Admin-Pass-2026!",
        "full_name": "Vikram Seth",
        "role": "SUPER_ADMIN",
        "branch": "Executive Platform Office",
        "phone": "+919876543200",
    },
    {
        "username": "ops1",
        "email": "ops1@kural.bank",
        "password": "Ops-Pass-2026!",
        "full_name": "Rajesh Kumar",
        "role": "OPS_MANAGER",
        "branch": "Central Banking Operations",
        "phone": "+919876543201",
    },
    {
        "username": "sup1",
        "email": "sup1@kural.bank",
        "password": "Sup-Pass-2026!",
        "full_name": "Sita Raman",
        "role": "SUPERVISOR",
        "branch": "Retail Branch Support",
        "phone": "+919876543202",
    },
    {
        "username": "agent1",
        "email": "agent1@kural.bank",
        "password": "Agent-Pass-2026!",
        "full_name": "Arun Verma",
        "role": "AGENT",
        "branch": "Frontline Customer Care",
        "phone": "+919876543203",
    },
    {
        "username": "comp1",
        "email": "comp1@kural.bank",
        "password": "Comp-Pass-2026!",
        "full_name": "Priya Nair",
        "role": "COMPLIANCE_OFFICER",
        "branch": "Risk & Regulatory Compliance",
        "phone": "+919876543204",
    },
    {
        "username": "auditor1",
        "email": "auditor1@kural.bank",
        "password": "Audit-Pass-2026!",
        "full_name": "Deepak Joshi",
        "role": "AUDITOR",
        "branch": "Internal Audit Directorate",
        "phone": "+919876543205",
    },
]

SAMPLE_AUDITS = [
    {
        "actor": "admin",
        "role": "SUPER_ADMIN",
        "action": "PLATFORM_HEALTH_CHECK",
        "resource_type": "SYSTEM",
        "resource_id": "CORE-SERVICES",
        "detail": "Verified Sarvam STT/TTS latency budgets (<1.5s) and database connection pool health",
        "minutes_ago": 8,
    },
    {
        "actor": "comp1",
        "role": "COMPLIANCE_OFFICER",
        "action": "CAMPAIGN_APPROVED",
        "resource_type": "CAMPAIGN",
        "resource_id": "CMP-FESTIVE-04",
        "detail": "Dual-control maker-checker approved KYC Update Campaign after checking DND scrub registry",
        "minutes_ago": 19,
    },
    {
        "actor": "ops1",
        "role": "OPS_MANAGER",
        "action": "DIALING_WINDOW_UPDATED",
        "resource_type": "CAMPAIGN",
        "resource_id": "CMP-FESTIVE-04",
        "detail": "Configured outbound pacing to 15 calls/min within TRAI compliant 09:00-19:00 window",
        "minutes_ago": 32,
    },
    {
        "actor": "sup1",
        "role": "SUPERVISOR",
        "action": "QA_CALL_REVIEWED",
        "resource_type": "RECORDING",
        "resource_id": "CALL-2026-9812",
        "detail": "Conducted QA quality review on escalated UPI refund dispute; marked call disposition as COMPLIANT",
        "minutes_ago": 45,
    },
    {
        "actor": "agent1",
        "role": "AGENT",
        "action": "CASE_RESOLVED",
        "resource_type": "CASE",
        "resource_id": "CASE-1042",
        "detail": "Assisted customer Subbu with mobile banking biometric unlock; confirmed OTP verified over secure channel",
        "minutes_ago": 60,
    },
    {
        "actor": "auditor1",
        "role": "AUDITOR",
        "action": "CONSENT_LEDGER_EXPORT",
        "resource_type": "REPORT",
        "resource_id": "AUD-CONSENT-Q3",
        "detail": "Exported immutable TRAI consent ledger audit trail for quarterly regulatory inspection",
        "minutes_ago": 110,
    },
]


def seed():
    db = Database()
    db.prepare_schema()
    now = datetime.now(timezone.utc)

    with db.session() as s:
        # 1. Upsert users
        for u in DEMO_USERS:
            existing = s.scalar(select(UserRow).where(UserRow.username == u["username"]))
            pwd_hash = hash_password(u["password"])
            if existing:
                existing.full_name = u["full_name"]
                existing.role = u["role"]
                existing.email = u["email"]
                existing.branch = u["branch"]
                existing.phone = u["phone"]
                existing.password_hash = pwd_hash
                existing.is_active = True
                user_id = existing.id
                print(f"[OK] Updated user: {u['username']} ({u['role']})")
            else:
                user_id = str(uuid4())
                new_user = UserRow(
                    id=user_id,
                    username=u["username"],
                    email=u["email"],
                    password_hash=pwd_hash,
                    full_name=u["full_name"],
                    role=u["role"],
                    branch=u["branch"],
                    phone=u["phone"],
                    is_active=True,
                )
                s.add(new_user)
                print(f"[OK] Created user: {u['username']} ({u['role']})")

            # 2. If agent1, link an AgentRow profile
            if u["username"] == "agent1":
                agent = s.scalar(select(AgentRow).where(AgentRow.user_id == user_id))
                if not agent:
                    agent = AgentRow(
                        agent_id="AGT-001",
                        user_id=user_id,
                        name=u["full_name"],
                        email=u["email"],
                        phone=u["phone"],
                        team="Customer Support Alpha",
                        availability="AVAILABLE",
                        skills_json=["UPI_DISPUTES", "SAVINGS_ACCOUNTS", "KYC_VERIFICATION"],
                        languages_json=["English", "Hindi", "Tamil"],
                        active_calls=0,
                    )
                    s.add(agent)
                    print(f"  -> Linked AgentRow profile for {u['username']}")

        # 3. Seed sample audit logs
        for a in SAMPLE_AUDITS:
            aid = f"AUD-{uuid4().hex[:8].upper()}"
            ts = now - timedelta(minutes=a["minutes_ago"])
            row = OperationsAuditEventRow(
                event_id=aid,
                actor=a["actor"],
                actor_role=a["role"],
                action=a["action"],
                resource_type=a["resource_type"],
                resource_id=a["resource_id"],
                ip="127.0.0.1",
                detail=a["detail"],
                timestamp=ts,
            )
            s.add(row)

        s.commit()
    print("\nAll 6 demo personas and activity records successfully seeded.")


if __name__ == "__main__":
    seed()
