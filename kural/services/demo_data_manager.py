"""Presentation Demo Data Manager: seed and reset rich banking data fixtures at a single click."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

from sqlalchemy import delete, func, select

from kural.persistence.database import Database
from kural.persistence.models import (
    AgentRow,
    CallbackRow,
    CallRecordRow,
    CampaignContactRow,
    CampaignRow,
    CaseEventRow,
    CaseRow,
    CustomerRow,
    OperationsAuditEventRow,
    SessionRow,
    UserRow,
)


def seed_presentation_fixtures(db: Database) -> dict[str, int]:
    """Seed comprehensive banking demo data across all platform hubs."""
    now = datetime.now(timezone.utc)

    CUSTOMERS = [
        {"customer_ref": "CUST-00001", "name": "Subbu Subramanian", "phone": "9876543210", "lang": "Tamil", "branch": "Chennai South", "region": "South", "acct": "SAVINGS", "app": "INSTALLED", "ver": "5.1.0"},
        {"customer_ref": "CUST-00002", "name": "Rajesh Sharma", "phone": "9876543211", "lang": "Hindi", "branch": "Delhi NCR", "region": "North", "acct": "CURRENT", "app": "NOT_INSTALLED", "ver": "—"},
        {"customer_ref": "CUST-00003", "name": "Priya Sundaram", "phone": "9876543212", "lang": "Tamil", "branch": "Bangalore East", "region": "South", "acct": "SAVINGS", "app": "OUTDATED", "ver": "4.8.2"},
        {"customer_ref": "CUST-00004", "name": "Amit Patel", "phone": "9876543213", "lang": "Hindi", "branch": "Mumbai Metro", "region": "West", "acct": "SAVINGS", "app": "INSTALLED", "ver": "5.2.1"},
        {"customer_ref": "CUST-00005", "name": "Sneha Reddy", "phone": "9876543214", "lang": "Telugu", "branch": "Hyderabad Central", "region": "South", "acct": "SALARY", "app": "INSTALLED", "ver": "5.2.0"},
        {"customer_ref": "CUST-00006", "name": "Rahul Mukherjee", "phone": "9876543215", "lang": "Bengali", "branch": "Kolkata East", "region": "East", "acct": "SAVINGS", "app": "NOT_INSTALLED", "ver": "—"},
        {"customer_ref": "CUST-00007", "name": "Ananya Deshmukh", "phone": "9876543216", "lang": "Marathi", "branch": "Pune Metro", "region": "West", "acct": "WEALTH", "app": "INSTALLED", "ver": "5.2.1"},
        {"customer_ref": "CUST-00008", "name": "Vikram Choudhary", "phone": "9876543217", "lang": "Hindi", "branch": "Jaipur North", "region": "North", "acct": "CURRENT", "app": "OUTDATED", "ver": "4.6.0"},
        {"customer_ref": "CUST-00009", "name": "Deepa Nair", "phone": "9876543218", "lang": "Malayalam", "branch": "Kochi Marine", "region": "South", "acct": "SAVINGS", "app": "INSTALLED", "ver": "5.2.1"},
        {"customer_ref": "CUST-00010", "name": "Gurpreet Singh", "phone": "9876543219", "lang": "Punjabi", "branch": "Chandigarh Hub", "region": "North", "acct": "SAVINGS", "app": "NOT_INSTALLED", "ver": "—"},
    ]

    CAMPAIGNS = [
        {
            "id": "CMP-DEMO-01",
            "name": "App Adoption & KYC Refresh · Q4",
            "objective": "App adoption",
            "status": "ACTIVE",
            "segment_size": 8200,
            "calls_dialed": 342,
            "answer_rate": 0.48,
            "langs": ["Hindi", "English", "Tamil"],
            "region": "All India",
            "category": "SERVICE",
        },
        {
            "id": "CMP-DEMO-02",
            "name": "Festive UPI & RuPay Digital Onboarding",
            "objective": "UPI activation",
            "status": "ACTIVE",
            "segment_size": 5600,
            "calls_dialed": 180,
            "answer_rate": 0.54,
            "langs": ["English", "Hindi", "Telugu"],
            "region": "South",
            "category": "SERVICE",
        },
        {
            "id": "CMP-DEMO-03",
            "name": "Senior Citizen FD & Tax Advisory",
            "objective": "Term deposit",
            "status": "DRAFT",
            "segment_size": 2100,
            "calls_dialed": 0,
            "answer_rate": 0.0,
            "langs": ["Hindi", "English"],
            "region": "West",
            "category": "ADVISORY",
        },
    ]

    CALLS = [
        {
            "call_id": "CALL-2026-9810",
            "cust": "CUST-00001",
            "phone": "9876543210",
            "intent": "CHECK_BALANCE",
            "disposition": "CLOSED",
            "duration": 142,
            "sentiment": 0.82,
            "mode": "AI",
            "summary": "Customer checked primary savings balance and recent UPI debit transaction.",
            "camp_id": "CMP-DEMO-01",
            "camp_name": "App Adoption & KYC Refresh · Q4",
            "branch": "Chennai South",
            "mins_ago": 15,
        },
        {
            "call_id": "CALL-2026-9811",
            "cust": "CUST-00002",
            "phone": "9876543211",
            "intent": "REPORT_FRAUD",
            "disposition": "ESCALATED",
            "duration": 215,
            "sentiment": -0.45,
            "mode": "AGENT",
            "summary": "Customer reported unrecognized ATM withdrawal; card blocked and dispute escalated.",
            "camp_id": None,
            "camp_name": "Direct Inbound",
            "branch": "Delhi NCR",
            "mins_ago": 35,
        },
        {
            "call_id": "CALL-2026-9812",
            "cust": "CUST-00003",
            "phone": "9876543212",
            "intent": "DISPUTE_TRANSACTION",
            "disposition": "ESCALATED",
            "duration": 184,
            "sentiment": -0.25,
            "mode": "AGENT",
            "summary": "UPI merchant debit double charge. Case registered under reference CASE-1041.",
            "camp_id": "CMP-DEMO-01",
            "camp_name": "App Adoption & KYC Refresh · Q4",
            "branch": "Bangalore East",
            "mins_ago": 55,
        },
        {
            "call_id": "CALL-2026-9813",
            "cust": "CUST-00004",
            "phone": "9876543213",
            "intent": "TRANSFER_FUNDS",
            "disposition": "CALLBACK_SCHEDULED",
            "duration": 96,
            "sentiment": 0.35,
            "mode": "AI",
            "summary": "Inquiry regarding IMPS limit increase; scheduled callback with branch advisor.",
            "camp_id": "CMP-DEMO-02",
            "camp_name": "Festive UPI & RuPay Digital Onboarding",
            "branch": "Mumbai Metro",
            "mins_ago": 80,
        },
        {
            "call_id": "CALL-2026-9814",
            "cust": "CUST-00005",
            "phone": "9876543214",
            "intent": "APP_HELP",
            "disposition": "CLOSED",
            "duration": 110,
            "sentiment": 0.90,
            "mode": "AI",
            "summary": "Guidance on biometric UPI PIN setup on Town Bank mobile app v5.2.",
            "camp_id": "CMP-DEMO-02",
            "camp_name": "Festive UPI & RuPay Digital Onboarding",
            "branch": "Hyderabad Central",
            "mins_ago": 120,
        },
        {
            "call_id": "CALL-2026-9815",
            "cust": "CUST-00006",
            "phone": "9876543215",
            "intent": "KYC_STATUS",
            "disposition": "CLOSED",
            "duration": 128,
            "sentiment": 0.70,
            "mode": "AI",
            "summary": "Confirmed Video KYC verification successfully completed via secure banking portal.",
            "camp_id": "CMP-DEMO-01",
            "camp_name": "App Adoption & KYC Refresh · Q4",
            "branch": "Kolkata East",
            "mins_ago": 160,
        },
    ]

    CASES = [
        {
            "id": "CASE-1041",
            "cust": "CUST-00001",
            "type": "UPI_DISPUTES",
            "priority": "High",
            "summary": "UPI payment charged (₹2,450) but merchant POS timed out",
            "category": "DISPUTES",
            "status": "RESOLVED",
            "notes": "Transaction reversed by NPCI clearing cycle; credit reflected in account.",
            "mins_ago": 90,
        },
        {
            "id": "CASE-1042",
            "cust": "CUST-00002",
            "type": "FRAUD_SECURITY",
            "priority": "Urgent",
            "summary": "Suspicious ATM withdrawal alert on international debit card",
            "category": "SECURITY",
            "status": "IN_PROGRESS",
            "notes": "Card temporarily blocked; customer confirming travel itinerary.",
            "mins_ago": 40,
        },
        {
            "id": "CASE-1043",
            "cust": "CUST-00003",
            "type": "APP_SUPPORT",
            "priority": "Normal",
            "summary": "Biometric face unlock failure on mobile app v4.8 after Android update",
            "category": "APP_SUPPORT",
            "status": "ASSIGNED",
            "notes": "Advised customer to clear app cache and re-register face biometric in settings.",
            "mins_ago": 70,
        },
        {
            "id": "CASE-1044",
            "cust": "CUST-00004",
            "type": "GENERAL_SUPPORT",
            "priority": "Normal",
            "summary": "International roaming SMS OTP delivery failure in Singapore",
            "category": "GENERAL_SUPPORT",
            "status": "NEW",
            "notes": "Customer traveling; requesting email OTP channel enablement.",
            "mins_ago": 15,
        },
    ]

    with db.session() as s:
        # 1. Upsert Customers
        for c in CUSTOMERS:
            existing = s.get(CustomerRow, c["customer_ref"])
            if not existing:
                s.add(
                    CustomerRow(
                        customer_ref=c["customer_ref"],
                        full_name=c["name"],
                        phone=c["phone"],
                        preferred_language=c["lang"],
                        branch=c["branch"],
                        region=c["region"],
                        account_type=c["acct"],
                        app_status=c["app"],
                        app_version=c["ver"],
                    )
                )

        # 2. Upsert Campaigns
        for camp in CAMPAIGNS:
            existing = s.get(CampaignRow, camp["id"])
            if not existing:
                s.add(
                    CampaignRow(
                        campaign_id=camp["id"],
                        name=camp["name"],
                        objective=camp["objective"],
                        status=camp["status"],
                        segment_size=camp["segment_size"],
                        calls_dialed=camp["calls_dialed"],
                        answer_rate=camp["answer_rate"],
                        languages_json=camp["langs"],
                        region=camp["region"],
                        category=camp["category"],
                    )
                )

        # 3. Add Campaign Contacts
        for cust in CUSTOMERS[:6]:
            cid = f"CNT-{cust['customer_ref'][-4:]}"
            existing = s.get(CampaignContactRow, cid)
            if not existing:
                s.add(
                    CampaignContactRow(
                        contact_id=cid,
                        campaign_id="CMP-DEMO-01",
                        customer_ref=cust["customer_ref"],
                        phone=cust["phone"],
                        status="COMPLETED" if int(cust["customer_ref"][-1]) % 2 == 0 else "PENDING",
                    )
                )

        # 4. Sessions & Call Records
        for cl in CALLS:
            sess_id = f"sess-{cl['call_id'].lower()}"
            if not s.get(SessionRow, sess_id):
                s.add(
                    SessionRow(
                        session_id=sess_id,
                        customer_ref=cl["cust"],
                        current_state="ENDED",
                        context_json={"intent": cl["intent"], "phone": cl["phone"]},
                    )
                )
                s.flush()
            if not s.get(CallRecordRow, cl["call_id"]):
                s.add(
                    CallRecordRow(
                        call_id=cl["call_id"],
                        session_id=sess_id,
                        customer_ref=cl["cust"],
                        masked_phone=f"+91 ••••• ••{cl['phone'][-3:]}",
                        language="Hindi",
                        branch=cl["branch"],
                        region="West",
                        started_at=now - timedelta(minutes=cl["mins_ago"]),
                        duration_sec=cl["duration"],
                        disposition=cl["disposition"],
                        status="COMPLETED",
                        resolution_mode=cl["mode"],
                        sentiment=cl["sentiment"],
                        summary=cl["summary"],
                        intent=cl["intent"],
                        campaign_id=cl["camp_id"],
                        campaign_name=cl["camp_name"],
                    )
                )

        # 5. Support Cases & Events
        for cs in CASES:
            sess_id = f"sess-case-{cs['id'].lower()}"
            if not s.get(SessionRow, sess_id):
                s.add(
                    SessionRow(
                        session_id=sess_id,
                        customer_ref=cs["cust"],
                        current_state="ESCALATED",
                    )
                )
                s.flush()
            if not s.get(CaseRow, cs["id"]):
                s.add(
                    CaseRow(
                        case_id=cs["id"],
                        session_id=sess_id,
                        customer_ref=cs["cust"],
                        case_type=cs["type"],
                        priority=cs["priority"],
                        summary=cs["summary"],
                        category=cs["category"],
                        status=cs["status"],
                        assigned_agent_id="AGT-001" if cs["status"] in ("IN_PROGRESS", "RESOLVED", "ASSIGNED") else None,
                        resolved_at=now if cs["status"] == "RESOLVED" else None,
                        resolution_notes=cs["notes"],
                        created_at=now - timedelta(minutes=cs["mins_ago"]),
                    )
                )

        # 6. Callbacks
        CALLBACKS = [
            {"id": "CBK-001", "cust": "CUST-00002", "mins": -30, "status": "OVERDUE", "notes": "Supervisor callback requested regarding debit card security alert"},
            {"id": "CBK-002", "cust": "CUST-00003", "mins": 60, "status": "SCHEDULED", "notes": "App biometric face reset walkthrough with Arun Verma"},
            {"id": "CBK-003", "cust": "CUST-00004", "mins": 180, "status": "SCHEDULED", "notes": "Follow up on international OTP SMS channel"},
        ]
        for cb in CALLBACKS:
            if not s.get(CallbackRow, cb["id"]):
                sess_id = f"sess-{cb['id'].lower()}"
                if not s.get(SessionRow, sess_id):
                    s.add(SessionRow(session_id=sess_id, customer_ref=cb["cust"], current_state="CALLBACK_SCHEDULED"))
                    s.flush()
                s.add(
                    CallbackRow(
                        callback_id=cb["id"],
                        session_id=sess_id,
                        customer_ref=cb["cust"],
                        status=cb["status"],
                        reason="APP_SUPPORT",
                        raw_expression=cb["notes"],
                        requested_text_normalized=cb["notes"],
                        scheduled_at_utc=now + timedelta(minutes=cb["mins"]),
                        scheduled_at_local=(now + timedelta(minutes=cb["mins"])).strftime("%Y-%m-%d %H:%M:%S"),
                        assigned_agent_id="AGT-001",
                    )
                )

        s.commit()

    return {
        "customers": len(CUSTOMERS),
        "campaigns": len(CAMPAIGNS),
        "calls": len(CALLS),
        "cases": len(CASES),
        "callbacks": 3,
    }


def reset_presentation_fixtures(db: Database) -> dict[str, str]:
    """Clean all demonstration fixtures (customers, campaigns, calls, cases, callbacks).
    Preserves all user accounts, passwords, and system administrator settings.
    """
    with db.session() as s:
        # Delete dependent children first
        s.execute(delete(CallbackRow))
        s.execute(delete(CaseEventRow))
        s.execute(delete(CaseRow))
        s.execute(delete(CallRecordRow))
        s.execute(delete(CampaignContactRow))
        s.execute(delete(CampaignRow))
        s.execute(delete(CustomerRow))
        s.execute(delete(SessionRow))
        s.commit()

    return {
        "status": "CLEAN",
        "message": "All presentation demo fixtures (customers, campaigns, calls, cases, callbacks) successfully cleared.",
    }


def get_demo_fixtures_status(db: Database) -> dict[str, Any]:
    """Return counts of demo fixtures currently present in the database."""
    with db.session() as s:
        cust_cnt = s.scalar(select(func.count(CustomerRow.customer_ref))) or 0
        camp_cnt = s.scalar(select(func.count(CampaignRow.campaign_id))) or 0
        call_cnt = s.scalar(select(func.count(CallRecordRow.call_id))) or 0
        case_cnt = s.scalar(select(func.count(CaseRow.case_id))) or 0
        cbk_cnt = s.scalar(select(func.count(CallbackRow.callback_id))) or 0

    has_data = (cust_cnt + camp_cnt + call_cnt + case_cnt + cbk_cnt) > 0
    return {
        "is_loaded": has_data,
        "customers_count": cust_cnt,
        "campaigns_count": camp_cnt,
        "calls_count": call_cnt,
        "cases_count": case_cnt,
        "callbacks_count": cbk_cnt,
        "summary": f"{cust_cnt} customers, {camp_cnt} campaigns, {call_cnt} calls, {case_cnt} cases" if has_data else "Pristine / Empty",
    }
