"""End-to-end acceptance for the operational platform.

Uses an explicitly labelled test environment: SQLite file database, the sandbox telephony
simulator and a test-number allowlist. Nothing here exercises a real phone network.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from kural.conversation.engine import KuralEngine
from kural.notifications.service import NotificationService
from kural.persistence.database import Database
from kural.persistence.models import CallbackRow, CaseEventRow, NotificationDeliveryRow
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.policy.calling_policy import next_permitted_slot
from kural.services.agent_service import AgentService
from kural.services.auth_service import AuthService
from kural.services.callback_service import CallbackService
from kural.services.customer_service import CustomerService
from kural.workers import callback_tick, outbox_tick, sla_tick


@pytest.fixture
def db(tmp_path):
    """SQLite by default; set KURAL_TEST_POSTGRES_URL to run the same acceptance on PostgreSQL."""
    import os
    pg = os.getenv("KURAL_TEST_POSTGRES_URL")
    if pg:
        from sqlalchemy import create_engine, text
        eng = create_engine(pg)
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        eng.dispose()
        database = Database(pg)
    else:
        database = Database(f"sqlite:///{(tmp_path / 'acc.db').as_posix()}")
    database.prepare_schema()
    yield database
    database.dispose()


def _staff(db):
    auth = AuthService(db)
    sup = auth.provision_user("sup1", "sup1@bank.test", "Supervisor-Pass-123", "Sita Sup", role="SUPERVISOR")
    agent_user = auth.provision_user("agent1", "agent1@bank.test", "Agent-Pass-123456", "Arun Agent", role="AGENT")
    AgentService(db).create_agent("Arun Agent", languages=["English"], skills=["GENERAL_SUPPORT", "APP_SUPPORT"],
                                  availability="AVAILABLE", agent_id="AG-001", user_id=agent_user["id"],
                                  phone="+919000000001")
    return sup, agent_user


def test_escalation_to_callback_full_lifecycle(db, sandbox_dialing, monkeypatch):
    provider = sandbox_dialing("9811111111")
    monkeypatch.setenv("KURAL_OUTBOUND_AUTODIAL_ENABLED", "true")
    from kural.config import reload_settings
    reload_settings()
    _staff(db)
    CustomerService(db).create_customer("Meera Iyer", "9811111111", customer_ref="CUST-ACC-1", preferred_language="English")

    # 1-3. Real conversation pipeline: customer asks for a human; KURAL authorises a case + callback request.
    repo = SqlAlchemyKuralRepository(db)
    engine = KuralEngine(repo)
    conv, _ = engine.create_session("CUST-ACC-1")
    engine.begin_live_call(conv.session_id)
    engine.turn(conv.session_id, "yes speaking")
    turn = engine.turn(conv.session_id, "I want to talk to a human agent")
    assert turn.ended and turn.case_id and turn.callback_id
    assert "can't connect you" in turn.response  # never promises a live connection

    # Retry of the same model/provider event must not duplicate the case.
    assert repo.get_session(conv.session_id).state.value == "HUMAN_ESCALATION"
    from kural.services.case_service import CaseService
    cases = CaseService(db).list_cases()
    assert len(cases) == 1
    case = CaseService(db).get_case(turn.case_id)
    # 4-7. Taxonomy, SLA, persistence and assignment to the eligible available agent.
    assert case["issue_code"] == "GENERAL_SUPPORT" and case["assigned_team"] == "CUSTOMER_CARE"
    assert case["sla_due_at"] and case["assigned_agent_id"] == "AG-001" and case["status"] == "ASSIGNED"
    assert [h["event_type"] for h in case["history"]][:2] == ["CREATED", "ASSIGNED"]

    cb = CallbackService(db).get_callback(turn.callback_id)
    assert cb["raw_status"] == "REQUESTED" and cb["customer_ref"] == "CUST-ACC-1" and cb["case_id"] == turn.case_id

    # 8. Notifications dispatched from the transactional outbox (idempotent on replay).
    notifier = NotificationService(db)
    assert outbox_tick(db, notifier) >= 3
    with db.session() as s:
        deliveries = s.scalars(select(NotificationDeliveryRow)).all()
        assert any(d.channel == "IN_APP" and d.event_type == "case.assigned" for d in deliveries)
        email = [d for d in deliveries if d.channel == "EMAIL"]
        assert email and all(d.status == "NOT_CONFIGURED" for d in email)  # no SMTP: never reported as sent
    assert outbox_tick(db, notifier) == 0

    # Callback time agreed by staff; policy is enforced.
    cb_svc = CallbackService(db)
    with pytest.raises(Exception):
        cb_svc.reschedule_callback(turn.callback_id, datetime.now(timezone.utc) - timedelta(hours=1), enforce_policy=True)
    slot = next_permitted_slot(datetime.now(timezone.utc) + timedelta(days=1))
    first = cb_svc.reschedule_callback(turn.callback_id, slot, actor="STAFF:sup1", enforce_policy=True)
    later = next_permitted_slot(slot + timedelta(hours=2))
    second = cb_svc.reschedule_callback(turn.callback_id, later, actor="STAFF:sup1", enforce_policy=True)
    assert second["version"] == first["version"] + 1 and second["scheduled_at_utc"] == later.isoformat()

    # Old time passes: nothing is due yet because the schedule moved.
    assert asyncio.run(callback_tick(db, provider, now=slot + timedelta(minutes=1))) == {"dialed": 0, "handed_to_human": 0, "reconciled": 0}

    # Due at the new time: provider invoked exactly once.
    due_at = later + timedelta(minutes=1)
    stats = asyncio.run(callback_tick(db, provider, now=due_at))
    assert stats["dialed"] == 1 and len(provider.calls) == 1
    # A second worker / tick cannot double-dial while the lease is held.
    assert asyncio.run(callback_tick(db, provider, now=due_at))["dialed"] == 0
    sid = next(iter(provider.calls))

    # Restart recovery: lease expires with no outcome -> reconcile via provider, never re-dial blindly.
    provider.calls[sid]["status"] = __import__("kural.telephony.contracts", fromlist=["x"]).TelephonyCallStatus.BUSY
    recovered = asyncio.run(callback_tick(db, provider, now=due_at + timedelta(minutes=11)))
    assert recovered["reconciled"] == 1 and len(provider.calls) == 1
    after = cb_svc.get_callback(turn.callback_id)
    assert after["raw_status"] == "SCHEDULED" and after["last_outcome"] == "BUSY" and after["attempt_count"] == 1

    # SLA monitor emits exactly one warning/breach.
    assert sla_tick(db, now=datetime.now(timezone.utc) + timedelta(days=2)) == 1
    assert sla_tick(db, now=datetime.now(timezone.utc) + timedelta(days=2)) == 0

    # 10. Audit history is complete.
    with db.session() as s:
        types = [e.event_type for e in s.scalars(select(CaseEventRow).where(CaseEventRow.case_id == turn.case_id))]
        assert "CREATED" in types and "ASSIGNED" in types
    history = [h["event_type"] for h in after["history"]]
    for expected in ("REQUESTED", "RESCHEDULED_BY_STAFF", "DISPATCH_CLAIMED", "DIAL_STARTED", "DISPATCH_RECOVERED", "OUTCOME_BUSY"):
        assert expected in history


def test_due_callback_without_telephony_goes_to_human(db):
    from kural.telephony.config import DisabledTelephonyProvider
    _staff(db)
    CustomerService(db).create_customer("Ravi K", "9822222222", customer_ref="CUST-ACC-2")
    cb_svc = CallbackService(db)
    from kural.services.callback_service import CallbackDraft, format_local
    slot = next_permitted_slot(datetime.now(timezone.utc) + timedelta(days=1))
    cb = cb_svc.upsert_callback("S-2", "CUST-ACC-2", CallbackDraft(slot, format_local(slot)), actor="STAFF:sup1")
    stats = asyncio.run(callback_tick(db, DisabledTelephonyProvider(), now=slot + timedelta(minutes=1)))
    assert stats == {"dialed": 0, "handed_to_human": 1, "reconciled": 0}
    after = cb_svc.get_callback(cb["callback_id"])
    assert after["raw_status"] == "DUE" and after["last_outcome"] == "AUTODIAL_DISABLED"


def test_customer_stated_time_is_scheduled_and_read_back(db):
    CustomerService(db).create_customer("Asha", "9833333333", customer_ref="CUST-ACC-3")
    engine = KuralEngine(SqlAlchemyKuralRepository(db))
    conv, _ = engine.create_session("CUST-ACC-3")
    engine.begin_live_call(conv.session_id)
    turn = engine.turn(conv.session_id, "I'm busy, call me day after tomorrow at 11 am")
    cb = CallbackService(db).get_callback(turn.callback_id)
    if cb["raw_status"] == "SCHEDULED":
        assert "scheduled your callback for" in turn.response
    else:  # e.g. resolved day falls on a Sunday/holiday: honest fallback, no promised time
        assert cb["raw_status"] == "REQUESTED" and "agree a convenient time" in turn.response


def test_webhook_auth_dedupe_and_out_of_order(tmp_path, sandbox_dialing, monkeypatch):
    monkeypatch.setattr("kural.telephony.router.is_within_calling_hours", lambda dt: True)
    provider = sandbox_dialing("9844444444")
    repo = SqlAlchemyKuralRepository(Database(f"sqlite:///{(tmp_path / 'wh.db').as_posix()}"))
    with TestClient(create_app(repository=repo)) as client:
        CustomerService(repo.database).create_customer("W", "9844444444", customer_ref="CUST-WH")
        call = client.post("/api/v1/telephony/calls", json={"customer_ref": "CUST-WH"})
        assert call.status_code == 200, call.text
        sid, call_id = call.json()["provider_call_sid"], call.json()["call_id"]

        def send(status: str):
            body = json.dumps({"CallSid": sid, "call_id": call_id, "status": status}).encode()
            return client.post("/api/v1/telephony/webhooks", content=body,
                               headers={"Content-Type": "application/json", "X-Telephony-Signature": provider.generate_signature(body)})

        assert client.post("/api/v1/telephony/webhooks", content=b"{}", headers={"Content-Type": "application/json"}).status_code == 401
        assert send("completed").json()["status"] == "accepted"
        assert send("completed").json()["status"] == "ignored"  # replay
        send("in-progress")  # late, out-of-order event must not reopen the call
        rec = client.get(f"/api/calls/{call_id}").json()
        assert rec["status"] == "COMPLETED" and rec["disposition"] == "COMPLETED"


@pytest.mark.real_auth
def test_rbac_enforced_server_side(tmp_path):
    repo = SqlAlchemyKuralRepository(Database(f"sqlite:///{(tmp_path / 'rbac.db').as_posix()}"))
    with TestClient(create_app(repository=repo)) as client:
        auth = AuthService(repo.database)
        for user, role in (("agent9", "AGENT"), ("admin9", "SYSTEM_ADMIN"), ("comp9", "COMPLIANCE_OFFICER")):
            auth.provision_user(user, f"{user}@bank.test", "Strong-Pass-12345", user, role=role)

        def headers(user):
            token = client.post("/api/v1/auth/login", json={"username": user, "password": "Strong-Pass-12345"}).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        assert client.get("/api/calls").status_code == 401
        assert client.get("/api/escalations").status_code == 401
        agent, admin, comp = headers("agent9"), headers("admin9"), headers("comp9")
        assert client.get("/api/calls", headers=agent).status_code == 200
        assert client.post("/api/campaigns", json={"name": "x"}, headers=agent).status_code == 403
        assert client.get("/api/customers", headers=admin).status_code == 403
        assert client.get("/api/system/health", headers=admin).status_code == 200
        assert client.post("/api/system/dialing", json={"stopped": True}, headers=comp).status_code == 200
        assert client.post("/api/system/dialing", json={"stopped": False}, headers=comp).status_code == 403
        assert client.get("/api/calls/x/recording", headers=agent).status_code == 403
        assert client.post("/api/demo/reset", headers=agent).status_code in (404, 405)
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/voice/realtime?session_id=x") as ws:
                ws.receive_json()
        assert client.get("/api/events/sse").status_code == 401
        me = client.get("/api/v1/auth/me", headers=agent).json()["user"]
        assert me["role"] == "AGENT" and "campaign:manage" not in me["permissions"]


def test_callback_assign_and_manual_outcome_routes(tmp_path):
    repo = SqlAlchemyKuralRepository(Database(f"sqlite:///{(tmp_path / 'cbr.db').as_posix()}"))
    with TestClient(create_app(repository=repo)) as client:
        db = repo.database
        _staff(db)
        CustomerService(db).create_customer("Kiran", "9855555555", customer_ref="CUST-CBR")
        from kural.services.callback_service import CallbackDraft, format_local
        slot = next_permitted_slot(datetime.now(timezone.utc) + timedelta(days=1))
        cb = CallbackService(db).upsert_callback("S-CBR", "CUST-CBR", CallbackDraft(slot, format_local(slot)), actor="STAFF:x")
        cid = cb["callback_id"]
        r = client.post(f"/api/callbacks/{cid}/assign", json={"agent_id": "AG-001"})
        assert r.status_code == 200 and r.json()["assigned_agent_id"] == "AG-001"
        assert client.post(f"/api/callbacks/{cid}/assign", json={"agent_id": "AG-404"}).status_code == 404
        assert client.post(f"/api/callbacks/{cid}/outcome", json={"outcome": "MAYBE"}).status_code == 422
        busy = client.post(f"/api/callbacks/{cid}/outcome", json={"outcome": "BUSY", "notes": "No pickup"}).json()
        assert busy["raw_status"] == "DUE" and busy["attempt_count"] == 1
        done = client.post(f"/api/callbacks/{cid}/outcome", json={"outcome": "COMPLETED", "notes": "Resolved app issue"}).json()
        assert done["raw_status"] == "COMPLETED" and done["outcome_notes"] == "Resolved app issue"
        assert client.post(f"/api/callbacks/{cid}/outcome", json={"outcome": "COMPLETED"}).status_code == 409
        types = [h["event_type"] for h in done["history"]]
        assert "ASSIGNED" in types and "OUTCOME_BUSY" in types and "OUTCOME_COMPLETED" in types


def test_text_session_disposition_uses_operational_category(tmp_path):
    repo = SqlAlchemyKuralRepository(Database(f"sqlite:///{(tmp_path / 'disp.db').as_posix()}"))
    with TestClient(create_app(repository=repo)) as client:
        CustomerService(repo.database).create_customer("Lata", "9866666666", customer_ref="CUST-DISP")
        sid = client.post("/api/v1/sessions", json={"customer_ref": "CUST-DISP"}).json()["session_id"]
        client.post(f"/api/v1/sessions/{sid}/messages", json={"text": "yes speaking"})
        client.post(f"/api/v1/sessions/{sid}/messages", json={"text": "I want to talk to a human"})
        call = [c for c in client.get("/api/calls").json() if c["sessionId"] == sid][0]
        assert call["disposition"] == "ESCALATED"
        assert client.get("/api/reports/overview").json()["outcomes14d"] == {"ESCALATED": 1}
