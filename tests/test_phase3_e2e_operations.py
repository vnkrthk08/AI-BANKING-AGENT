"""End-to-end integration test verifying complete banking operations workflow across all 10 Phase 3 domains."""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from kural.persistence.database import Database
from kural.persistence.models import CallbackRow
from kural.persistence.repository import SqlAlchemyKuralRepository


@pytest.fixture
def client(sandbox_dialing):
    sandbox_dialing("9876543290")
    db = Database("sqlite:///:memory:")
    repo = SqlAlchemyKuralRepository(db)
    app = create_app(repository=repo)
    with TestClient(app) as test_client:
        yield test_client


def test_full_banking_operations_lifecycle(client: TestClient):
    # -------------------------------------------------------------
    # 1. Customer Import & DND Scrub
    # -------------------------------------------------------------
    csv_customers = """full_name,phone,language,app_status,dnd,branch,region
Rohan Mehra,9876543290,Hindi,INSTALLED,0,Delhi NCR,North
Smita Sen,9876543291,Bengali,NOT_INSTALLED,1,Kolkata East,East
"""
    imp_resp = client.post("/api/customers/import", content=csv_customers.encode("utf-8"))
    assert imp_resp.status_code == 200
    assert imp_resp.json()["imported"] == 2
    assert imp_resp.json()["dnd_suppressed"] == 1

    rohan = client.get("/api/customers/+919876543290")
    # Phone search via list endpoint
    search_resp = client.get("/api/customers?search=9876543290")
    assert search_resp.status_code == 200
    customers = search_resp.json()
    assert len(customers) == 1
    cust = customers[0]
    cust_ref = cust["customer_ref"]
    assert cust["full_name"] == "Rohan Mehra"
    assert cust["dnd_status"] is False

    # -------------------------------------------------------------
    # 2. Campaign Creation & Contact Enrollment
    # -------------------------------------------------------------
    camp_resp = client.post("/api/campaigns", json={
        "name": "Q4 Digital Support Outreach",
        "objective": "Service support",
        "scriptVersion": "v2.0",
        "maxAttempts": 3,
        "retryGapHours": 24,
        "languages": ["Hindi", "English"],
        "region": "North",
    })
    assert camp_resp.status_code == 200
    campaign = camp_resp.json()
    camp_id = campaign["id"]
    assert campaign["status"] == "DRAFT"

    # Enroll contact
    csv_contacts = f"customer_ref,phone\n{cust_ref},+919876543290\n"
    enroll_resp = client.post(f"/api/campaigns/{camp_id}/contacts/import", content=csv_contacts.encode("utf-8"))
    assert enroll_resp.status_code == 200
    assert enroll_resp.json()["added"] == 1

    # -------------------------------------------------------------
    # 3. Campaign Activation
    # -------------------------------------------------------------
    assert client.post(f"/api/campaigns/{camp_id}/approve").status_code == 200
    start_resp = client.post(f"/api/campaigns/{camp_id}/start")
    assert start_resp.status_code == 200, start_resp.text
    assert start_resp.json()["status"] == "ACTIVE"

    # -------------------------------------------------------------
    # 4. Outbound Call Placement & Voice Turn Execution
    # -------------------------------------------------------------
    # Start session for Rohan
    sess_resp = client.post("/api/v1/sessions", json={"customer_ref": cust_ref})
    assert sess_resp.status_code == 200
    session_id = sess_resp.json()["session_id"]

    # Customer confirms identity
    t1 = client.post(f"/api/v1/sessions/{session_id}/messages", json={"text": "Yes, this is Rohan speaking."})
    assert t1.status_code == 200

    # Customer reports login problem and shares card details
    t2 = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"text": "I cannot login to the mobile app. My card number is 4111-2222-3333-4444 and phone is 9876543290."},
    )
    assert t2.status_code == 200

    # -------------------------------------------------------------
    # 5. Support Case / Ticket Creation
    # -------------------------------------------------------------
    case_resp = client.post("/api/escalations", json={
        "session_id": session_id,
        "customer_ref": cust_ref,
        "issue_code": "LOGIN_ISSUE",
        "summary": "Customer cannot login to the mobile app.",
        "key_lines": ["I cannot login to the mobile app."],
        "actions_tried": ["App restart"],
    })
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    case_id = case_data["id"]
    assert case_data["status"] == "NEW"
    assert case_data["category"] == "LOGIN_ISSUE"
    assert case_data["priority"] == "High"

    # -------------------------------------------------------------
    # 6. Human Representative Assignment
    # -------------------------------------------------------------
    from tests.conftest import seed_test_agents
    seed_test_agents(client.app.state.database)
    assign_resp = client.post("/api/agents/assign", json={
        "language": "Hindi",
        "category": "LOGIN_ISSUE",
    })
    assert assign_resp.status_code == 200
    assigned_agent = assign_resp.json()["assigned_agent"]
    assert assigned_agent is not None
    agent_id = assigned_agent["id"]

    # Assign case to agent
    patch_case = client.patch(f"/api/escalations/{case_id}", json={
        "assigned_agent_id": agent_id,
        "status": "ASSIGNED",
    })
    assert patch_case.status_code == 200
    assert patch_case.json()["status"] == "ASSIGNED"

    # -------------------------------------------------------------
    # 7. Callback Scheduling & Execution
    # -------------------------------------------------------------
    tomorrow_utc = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    cb_resp = client.post("/api/callbacks", json={
        "session_id": session_id,
        "customer_ref": cust_ref,
        "case_id": case_id,
        "scheduled_at_utc": tomorrow_utc,
        "reason": "LOGIN_ASSISTANCE",
    })
    assert cb_resp.status_code == 200
    cb_data = cb_resp.json()
    cb_id = cb_data["id"]
    assert cb_data["status"] == "SCHEDULED"

    # Reschedule callback to earlier
    earlier_utc = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    resched_resp = client.post(f"/api/callbacks/{cb_id}/reschedule", json={
        "scheduled_at_utc": earlier_utc,
        "actor": "STAFF",
    })
    assert resched_resp.status_code == 200

    # -------------------------------------------------------------
    # 8. Call Log, Redacted Transcript, and Audio Recording
    # -------------------------------------------------------------
    calls = client.get("/api/calls").json()
    my_call = next((c for c in calls if c.get("sessionId") == session_id), None)
    assert my_call is not None
    call_id = my_call["id"]

    # Redacted transcript check
    transcript = client.get(f"/api/calls/{call_id}/transcript").json()
    assert len(transcript) >= 2
    # Check that credit card and phone are masked in transcript
    user_turns = [t for t in transcript if t["speaker"] == "CUSTOMER"]
    assert any("[REDACTED_CARD]" in t["text"] or "XXXX-XXXX-XXXX-4444" in t["text"] for t in user_turns)
    assert any("+91 98XXX XX90" in t["text"] for t in user_turns)

    # Audio recording check
    rec_resp = client.get(f"/api/calls/{call_id}/recording")
    assert rec_resp.status_code == 404  # text session: no audio captured, none fabricated

    # -------------------------------------------------------------
    # 9. Dashboard Operational Snapshot Verification
    # -------------------------------------------------------------
    snap_resp = client.get("/api/snapshot")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()

    assert any(c["id"] == camp_id for c in snap["campaigns"])
    assert any(c["id"] == case_id for c in snap["escalations"])
    assert any(c["id"] == cb_id for c in snap["callbacks"])
    assert any(c["id"] == call_id for c in snap["calls"])
    assert len(snap["agents"]) == 16
    assert len(snap["workloads"]) == 16

    # -------------------------------------------------------------
    # 10. Operational KPIs and Reporting
    # -------------------------------------------------------------
    kpis = client.get("/api/reports/kpi-summary").json()
    assert kpis["callsDialed"] >= 1

    audit_entry = client.post("/api/audit", json={
        "action": "E2E_VERIFICATION_COMPLETE",
        "resourceType": "WORKFLOW",
        "resourceId": session_id,
        "role": "OPS_MANAGER",
        "detail": "End to end operational banking test completed successfully.",
    }).json()
    assert audit_entry["action"] == "E2E_VERIFICATION_COMPLETE"
