"""Acceptance tests AT-CB-1 through AT-CB-7 per Spec §7.9 and Case tests per Spec §9."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from zoneinfo import ZoneInfo

from app.main import create_app
from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.services.callback_service import CallbackDraft, CallbackService, KOLKATA_TZ
from kural.services.case_service import CaseService


@pytest.fixture
def clean_db(tmp_path):
    db_file = tmp_path / "test_callback_acceptance.db"
    db = Database(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(db.engine)
    yield db
    db.dispose()


@pytest.fixture
def client(clean_db):
    repo = SqlAlchemyKuralRepository(clean_db)
    app = create_app(repository=repo)
    with TestClient(app) as test_client:
        yield test_client


def test_at_cb_1_customer_confirms_callback_appears_in_dashboard(clean_db, client):
    """AT-CB-1: Customer confirms 'tomorrow 5' -> dashboard shows one SCHEDULED callback at Wed 7 Oct 5:00 PM."""
    # Wed 7 Oct 2026, 17:00 IST = 11:30 UTC
    scheduled_utc = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    scheduled_local = "Wednesday, 7 October, 5:00 PM IST"

    response = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-1",
            "customer_ref": "C48291",
            "scheduled_at_utc": scheduled_utc.isoformat(),
            "scheduled_at_local": scheduled_local,
            "raw_expression": "tomorrow at 5",
            "reason": "CUSTOMER_BUSY",
            "resolution_rule": "R1+R4",
        },
    )
    assert response.status_code == 200
    cb_data = response.json()
    assert cb_data["status"] == "SCHEDULED"
    assert cb_data["version"] == 1
    assert cb_data["customer_ref"] == "C48291"
    assert "5:00 PM" in cb_data["scheduled_at_local"]

    # Dashboard polling/querying shows this callback
    list_resp = client.get("/api/callbacks")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["callback_id"] == cb_data["callback_id"]
    assert items[0]["status"] == "SCHEDULED"


def test_at_cb_2_reschedule_same_call_updates_same_record_and_shows_moved(clean_db, client):
    """AT-CB-2: Customer changes to 6 PM in same call -> SAME callback_id, version 2, shows 'Moved from 5:00 PM'."""
    dt_5pm = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    resp1 = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-2",
            "customer_ref": "C48291",
            "scheduled_at_utc": dt_5pm.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 5:00 PM IST",
            "raw_expression": "tomorrow at 5",
        },
    )
    assert resp1.status_code == 200
    first_cb = resp1.json()
    original_id = first_cb["callback_id"]
    assert first_cb["version"] == 1

    # Customer says: "actually make it 6"
    dt_6pm = datetime(2026, 10, 7, 12, 30, tzinfo=timezone.utc)
    resp2 = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-2",
            "customer_ref": "C48291",
            "scheduled_at_utc": dt_6pm.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 6:00 PM IST",
            "raw_expression": "actually make it 6",
        },
    )
    assert resp2.status_code == 200
    second_cb = resp2.json()

    # Same callback_id, version 2
    assert second_cb["callback_id"] == original_id
    assert second_cb["version"] == 2
    assert second_cb["status"] == "SCHEDULED"
    assert "Moved from" in second_cb["moved_label"]
    assert "5:00 PM" in second_cb["moved_label"]
    assert len(second_cb["history"]) == 2
    assert second_cb["history"][1]["event_type"] == "RESCHEDULED_BY_CUSTOMER"

    # Dashboard has still exactly 1 record for this call
    list_resp = client.get("/api/callbacks")
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["callback_id"] == original_id
    assert items[0]["version"] == 2


def test_at_cb_3_customer_cancels_status_cancelled(clean_db, client):
    """AT-CB-3: Customer cancels -> status CANCELLED; visible in history."""
    dt = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    create_resp = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-3",
            "customer_ref": "C48291",
            "scheduled_at_utc": dt.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 5:00 PM IST",
        },
    )
    cb_id = create_resp.json()["callback_id"]

    # Cancel callback
    cancel_resp = client.post(f"/api/callbacks/{cb_id}/cancel")
    assert cancel_resp.status_code == 200
    cancelled_cb = cancel_resp.json()
    assert cancelled_cb["status"] == "CANCELLED"

    history_types = [h["event_type"] for h in cancelled_cb["history"]]
    assert "CANCELLED_BY_CUSTOMER" in history_types


def test_at_cb_4_retry_idempotency_returns_same_record(clean_db, client):
    """AT-CB-4: Retry of commit API with same key -> still one record."""
    scheduled_utc = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    idem_key = "CALL-AT-CB-4:callback:none"

    resp1 = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-4",
            "customer_ref": "C48291",
            "scheduled_at_utc": scheduled_utc.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 5:00 PM IST",
            "idempotency_key": idem_key,
        },
    )
    assert resp1.status_code == 200
    id1 = resp1.json()["callback_id"]

    # Immediate retry with same idempotency key (e.g. network retry)
    resp2 = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-4",
            "customer_ref": "C48291",
            "scheduled_at_utc": scheduled_utc.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 5:00 PM IST",
            "idempotency_key": idem_key,
        },
    )
    assert resp2.status_code == 200
    id2 = resp2.json()["callback_id"]

    assert id1 == id2
    assert resp2.json()["version"] == 1

    # Verify only 1 row exists in DB
    all_callbacks = client.get("/api/callbacks").json()
    assert len(all_callbacks) == 1


def test_at_cb_5_staff_reschedules_in_dashboard(clean_db, client):
    """AT-CB-5: Staff reschedules in dashboard -> history shows staff actor; uses new time."""
    scheduled_utc = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    create_resp = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-5",
            "customer_ref": "C48291",
            "scheduled_at_utc": scheduled_utc.isoformat(),
            "scheduled_at_local": "Wednesday, 7 October, 5:00 PM IST",
        },
    )
    cb_id = create_resp.json()["callback_id"]

    # Staff reschedules via PATCH /api/callbacks/{id}
    new_utc = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)  # 5:30 PM IST
    patch_resp = client.patch(
        f"/api/callbacks/{cb_id}",
        json={
            "preferredAt": new_utc.isoformat(),
            "actor": "STAFF-ALICE",
        },
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["version"] == 2
    assert "STAFF" in updated["history"][-1]["actor"]
    assert updated["history"][-1]["event_type"] == "RESCHEDULED_BY_STAFF"
    assert "5:30 PM" in updated["scheduled_at_local"]


def test_at_cb_6_timezone_utc_1230_displays_600_pm_ist():
    """AT-CB-6: Timezone: stored UTC 12:30Z displays 6:00 PM IST."""
    utc_time = datetime(2026, 10, 7, 12, 30, tzinfo=timezone.utc)
    ist_time = utc_time.astimezone(KOLKATA_TZ)
    assert ist_time.hour == 18
    assert ist_time.minute == 0
    formatted = ist_time.strftime("%I:%M %p IST")
    assert formatted == "06:00 PM IST"


def test_at_cb_7_callback_without_case_has_customer_busy_reason(clean_db, client):
    """AT-CB-7: Callback without case (simple busy) appears in dashboard with reason CUSTOMER_BUSY."""
    scheduled_utc = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    resp = client.post(
        "/api/callbacks",
        json={
            "session_id": "CALL-AT-CB-7",
            "customer_ref": "C48291",
            "scheduled_at_utc": scheduled_utc.isoformat(),
            "reason": "CUSTOMER_BUSY",
            "case_id": None,
        },
    )
    assert resp.status_code == 200
    cb = resp.json()
    assert cb["reason"] == "CUSTOMER_BUSY"
    assert cb["case_id"] is None


def test_case_creation_and_idempotency(clean_db, client):
    """Test Case service per Spec §9.1-§9.4."""
    # 1. Urgent fraud case
    fraud_resp = client.post(
        "/api/cases",
        json={
            "session_id": "CALL-FRAUD-1",
            "customer_ref": "C48291",
            "issue_code": "SECURITY_CONCERN",
            "summary": "Customer reported OTP shared",
        },
    )
    assert fraud_resp.status_code == 200
    fraud_case = fraud_resp.json()
    assert fraud_case["priority"] == "Urgent"
    assert fraud_case["assigned_team"] == "SECURITY_DESK"
    assert fraud_case["case_type"] == "SECURITY"

    # 2. Idempotency on {call_id}:case:{issue_code}
    retry_resp = client.post(
        "/api/cases",
        json={
            "session_id": "CALL-FRAUD-1",
            "customer_ref": "C48291",
            "issue_code": "SECURITY_CONCERN",
            "summary": "Duplicate attempt",
        },
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["case_id"] == fraud_case["case_id"]

    # 3. High priority login issue case
    login_resp = client.post(
        "/api/cases",
        json={
            "session_id": "CALL-APP-1",
            "customer_ref": "C48291",
            "issue_code": "LOGIN_ISSUE",
            "summary": "Cannot log into app",
        },
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["priority"] == "High"
    assert login_resp.json()["assigned_team"] == "APP_SUPPORT"
