"""Integration tests for Phase 3 Bank Operations & Automation REST APIs."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from kural.persistence.database import Database
from kural.persistence.repository import SqlAlchemyKuralRepository


@pytest.fixture
def client():
    db = Database("sqlite:///:memory:")
    repo = SqlAlchemyKuralRepository(db)
    app = create_app(repository=repo)
    with TestClient(app) as test_client:
        yield test_client


def test_customer_apis(client: TestClient):
    # 1. Create customer
    resp = client.post("/api/customers", json={
        "full_name": "Anita Desai",
        "phone": "9876543220",
        "email": "anita@example.com",
        "preferred_language": "Hindi",
        "branch": "Mumbai Metro",
        "region": "West",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    cust_ref = data["customer_ref"]
    assert data["full_name"] == "Anita Desai"
    assert data["phone"] == "+91 ••••• ••220"  # API never returns raw numbers

    # 2. Get customer
    get_resp = client.get(f"/api/customers/{cust_ref}")
    assert get_resp.status_code == 200
    assert get_resp.json()["customer_ref"] == cust_ref

    # 3. List customers
    list_resp = client.get("/api/customers?search=Anita")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 4. Import customers CSV
    csv_content = """full_name,phone,language
Karan Johar,9876543221,Hindi
Deepa Nair,9876543222,Tamil
"""
    imp_resp = client.post("/api/customers/import", content=csv_content.encode("utf-8"))
    assert imp_resp.status_code == 200
    assert imp_resp.json()["imported"] == 2

    # 5. Export customers CSV
    exp_resp = client.get("/api/customers/export")
    assert exp_resp.status_code == 200
    assert "Karan Johar" in exp_resp.text


def test_campaign_apis(client: TestClient, sandbox_dialing):
    sandbox_dialing("9876543231", "9876543232")
    # 1. Create campaign
    create_resp = client.post("/api/campaigns", json={
        "name": "Festive Promo Q4",
        "objective": "Credit card upgrade",
        "scriptVersion": "v1.2",
        "maxAttempts": 2,
        "languages": ["Hindi", "English"],
        "region": "West",
    })
    assert create_resp.status_code == 200
    camp = create_resp.json()
    cid = camp["id"]
    assert camp["name"] == "Festive Promo Q4"
    assert camp["status"] == "DRAFT"

    # 2. Unapproved campaign cannot start (fail-closed preflight)
    blocked = client.post(f"/api/campaigns/{cid}/start")
    assert blocked.status_code == 409

    # 3. Import contacts to campaign
    csv_contacts = """customer_ref,phone
CUST-001,9876543231
CUST-002,9876543232
"""
    imp_resp = client.post(f"/api/campaigns/{cid}/contacts/import", content=csv_contacts.encode("utf-8"))
    assert imp_resp.status_code == 200
    assert imp_resp.json()["added"] == 2

    # 4. Approve, start, pause
    assert client.post(f"/api/campaigns/{cid}/approve").json()["status"] == "APPROVED"
    start_resp = client.post(f"/api/campaigns/{cid}/start")
    assert start_resp.status_code == 200, start_resp.text
    assert start_resp.json()["status"] == "ACTIVE"
    pause_resp = client.post(f"/api/campaigns/{cid}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "PAUSED"


def test_call_and_recording_apis(client: TestClient):
    # 1. Create session (which creates call record)
    sess_resp = client.post("/api/v1/sessions", json={"customer_ref": "demo-001"})
    assert sess_resp.status_code == 200
    session_id = sess_resp.json()["session_id"]

    # 2. List calls
    calls_resp = client.get("/api/calls")
    assert calls_resp.status_code == 200
    calls = calls_resp.json()
    matching = [c for c in calls if c.get("sessionId") == session_id]
    assert len(matching) == 1
    call_id = matching[0]["id"]

    # 3. Get single call
    single_resp = client.get(f"/api/calls/{call_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["id"] == call_id

    # 4. Get transcript (with PII redaction)
    transcript_resp = client.get(f"/api/calls/{call_id}/transcript")
    assert transcript_resp.status_code == 200
    assert isinstance(transcript_resp.json(), list)

    # 5. No recording was captured, so none is served (never a fabricated file)
    rec_resp = client.get(f"/api/calls/{call_id}/recording")
    assert rec_resp.status_code == 404

    # 6. Export calls CSV
    exp_resp = client.get("/api/calls/export")
    assert exp_resp.status_code == 200
    assert call_id in exp_resp.text


def test_agent_and_assignment_apis(client: TestClient):
    from tests.conftest import seed_test_agents
    seed_test_agents(client.app.state.database)
    # 1. List agents and workloads
    agent_resp = client.get("/api/agents")
    assert agent_resp.status_code == 200
    payload = agent_resp.json()
    assert "agents" in payload
    assert len(payload["agents"]) == 16
    assert "workloads" in payload
    assert "slaPolicies" in payload

    # 2. Patch agent status
    patch_resp = client.patch("/api/agents/AG-001/status", json={"availability": "ON_CALL"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["availability"] == "ON_CALL"

    # 3. Auto-assign resource
    assign_resp = client.post("/api/agents/assign", json={"language": "Tamil", "category": "APP_SUPPORT"})
    assert assign_resp.status_code == 200
    assert "assigned_agent" in assign_resp.json()
    assert "Tamil" in assign_resp.json()["assigned_agent"]["languages"]


def test_compliance_and_audit_apis(client: TestClient):
    # 1. Compliance summary
    comp_resp = client.get("/api/compliance/summary")
    assert comp_resp.status_code == 200
    assert "consents" in comp_resp.json()

    # 2. Record operational audit
    post_audit = client.post("/api/audit", json={
        "action": "POLICY_REVIEWED",
        "resourceType": "POLICY",
        "resourceId": "POL-01",
        "role": "COMPLIANCE",
        "detail": "Verified SLA guidelines.",
    })
    assert post_audit.status_code == 200
    assert post_audit.json()["action"] == "POLICY_REVIEWED"

    # 3. List operational audits
    list_audits = client.get("/api/audit")
    assert list_audits.status_code == 200
    assert len(list_audits.json()) >= 1


def test_reports_and_snapshot_apis(client: TestClient):
    # 1. KPI summary
    kpi_resp = client.get("/api/reports/kpi-summary")
    assert kpi_resp.status_code == 200
    assert "callsDialed" in kpi_resp.json()

    # 2. Report schedules
    sched_resp = client.post("/api/reports/schedules", json={
        "cadence": "DAILY",
        "time": "10:00",
        "formats": ["PDF"],
        "recipient": "compliance@townbank.demo",
    })
    assert sched_resp.status_code == 200
    assert sched_resp.json()["recipient"] == "compliance@townbank.demo"

    get_scheds = client.get("/api/reports/schedules")
    assert get_scheds.status_code == 200
    assert len(get_scheds.json()) >= 1

    # 3. Full combined snapshot
    snap_resp = client.get("/api/snapshot")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert "calls" in snap
    assert "campaigns" in snap
    assert "callbacks" in snap
    assert "escalations" in snap
    assert "agents" in snap
    assert "workloads" in snap
    assert "slaPolicies" in snap
    assert "consents" in snap
    assert "auditEvents" in snap
