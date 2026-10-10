"""Comprehensive tests for vendor-neutral telephony integration, regulatory calling policies,
durable in-app notifications, and human escalation/callback workflows.
"""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from kural.persistence.database import Database
from kural.persistence.models import CustomerRow, CaseRow, CallbackRow
from kural.policy.calling_policy import is_sunday, is_within_calling_hours, CallingPolicyEngine
from kural.telephony.config import set_telephony_provider, get_telephony_provider, DisabledTelephonyProvider
from kural.telephony.contracts import TelephonyCallRequest, TelephonyCallStatus, TelephonyProviderStatus
from kural.telephony.exotel import ExotelTelephonyProvider
from kural.telephony.sandbox import SandboxTelephonyProvider
from kural.notifications.service import NotificationService


KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def test_app():
    app = create_app()
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


def test_disabled_telephony_provider_truthfulness():
    provider = DisabledTelephonyProvider()
    assert not provider.is_configured
    assert provider.provider_name == "disabled"


def test_disabled_telephony_provider_behavior():
    async def _run():
        provider = DisabledTelephonyProvider()
        health = await provider.health_check()
        assert health.status == TelephonyProviderStatus.NOT_CONFIGURED
        assert not health.is_live

        req = TelephonyCallRequest(
            to_phone="+91 98765 43210",
            from_phone="+91 1800 200 4400",
            customer_ref="CUST-001",
            call_id="CALL-001",
        )
        res = await provider.initiate_call(req)
        assert not res.success
        assert res.error_code == "TELEPHONY_DISABLED"

    asyncio.run(_run())


def test_exotel_provider_unconfigured_truthfulness():
    provider = ExotelTelephonyProvider(api_key="", api_token="", account_sid="", caller_id="")
    assert not provider.is_configured
    assert provider.provider_name == "exotel"


def test_exotel_provider_unconfigured_call_rejected():
    async def _run():
        provider = ExotelTelephonyProvider(api_key="", api_token="", account_sid="", caller_id="")
        req = TelephonyCallRequest(
            to_phone="+91 98765 43210",
            from_phone="+91 1800 200 4400",
            customer_ref="CUST-001",
            call_id="CALL-001",
        )
        res = await provider.initiate_call(req)
        assert not res.success
        assert res.error_code == "PROVIDER_NOT_CONFIGURED"

        health = await provider.health_check()
        assert health.status == TelephonyProviderStatus.NOT_CONFIGURED
        assert not health.is_live

    asyncio.run(_run())


def test_sandbox_telephony_lifecycle():
    async def _run():
        sandbox = SandboxTelephonyProvider()
        assert sandbox.is_configured
        assert sandbox.provider_name == "sandbox"

        health = await sandbox.health_check()
        assert health.is_live
        assert health.status == TelephonyProviderStatus.HEALTHY

        req = TelephonyCallRequest(
            to_phone="+91 98765 43210",
            from_phone="+91 1800 200 4400",
            customer_ref="CUST-100",
            call_id="CALL-100",
        )
        init_res = await sandbox.initiate_call(req)
        assert init_res.success
        assert init_res.status == TelephonyCallStatus.INITIATED
        sid = init_res.provider_call_sid
        assert sid.startswith("SANDBOX-SID-")

        # Status check
        st_res = await sandbox.get_call_status(sid)
        assert st_res.success
        assert st_res.status == TelephonyCallStatus.INITIATED

        # Transfer to agent
        tx_res = await sandbox.transfer_to_agent(sid, "+91 98765 00001", "AGT-007")
        assert tx_res.success
        assert tx_res.status == "BRIDGED"

        # Hangup
        hangup_res = await sandbox.hangup_call(sid)
        assert hangup_res is True

        st_after = await sandbox.get_call_status(sid)
        assert st_after.status == TelephonyCallStatus.COMPLETED

    asyncio.run(_run())


def test_calling_policy_rules():
    # Sunday check (2026-10-11 is a Sunday)
    sunday_dt = datetime(2026, 10, 11, 10, 0, 0, tzinfo=KOLKATA_TZ)
    assert is_sunday(sunday_dt) is True

    # Monday check (2026-10-12 is a Monday)
    monday_dt = datetime(2026, 10, 12, 10, 0, 0, tzinfo=KOLKATA_TZ)
    assert is_sunday(monday_dt) is False

    # Calling hours check (09:00 - 19:00 IST)
    morning_early = datetime(2026, 10, 12, 8, 30, 0, tzinfo=KOLKATA_TZ)
    assert is_within_calling_hours(morning_early) is False

    valid_time = datetime(2026, 10, 12, 14, 0, 0, tzinfo=KOLKATA_TZ)
    assert is_within_calling_hours(valid_time) is True

    evening_late = datetime(2026, 10, 12, 19, 30, 0, tzinfo=KOLKATA_TZ)
    assert is_within_calling_hours(evening_late) is False


def test_telephony_api_endpoints(test_app, client):
    sandbox = SandboxTelephonyProvider()
    set_telephony_provider(sandbox)

    # 1. Telephony Status
    resp = client.get("/api/v1/telephony/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "sandbox"
    assert data["is_live"] is True

    # 2. Webhook verification with HMAC
    webhook_payload = b'{"event_id":"EVT-1","CallSid":"SANDBOX-SID-TEST","status":"completed","duration_sec":42}'
    valid_sig = sandbox.generate_signature(webhook_payload)

    # Reject invalid signature
    bad_resp = client.post(
        "/api/v1/telephony/webhooks",
        content=webhook_payload,
        headers={"Content-Type": "application/json", "X-Telephony-Signature": "bad-sig"},
    )
    assert bad_resp.status_code == 401

    # Accept valid signature
    good_resp = client.post(
        "/api/v1/telephony/webhooks",
        content=webhook_payload,
        headers={"Content-Type": "application/json", "X-Telephony-Signature": valid_sig},
    )
    assert good_resp.status_code == 200
    assert good_resp.json()["status"] == "accepted"


def test_notifications_lifecycle(test_app, client):
    db: Database = test_app.state.database
    svc = NotificationService(db)

    # Create notifications
    n1 = svc.create_notification(
        title="Escalation Alert",
        message="High priority escalation for customer CUST-001",
        level="WARNING",
        category="ESCALATION",
    )
    assert n1["id"].startswith("NOTIF-")
    assert n1["is_read"] is False

    n2 = svc.create_notification(
        title="Callback Alert",
        message="Callback due for customer CUST-002",
        level="INFO",
        category="CALLBACK",
    )

    # List notifications
    listed = svc.list_notifications()
    assert len(listed) >= 2
    assert svc.get_unread_count() >= 2

    # Mark as read via API
    patch_resp = client.patch(f"/api/notifications/{n1['id']}/read")
    assert patch_resp.status_code == 200
    assert patch_resp.json()["success"] is True

    # Check unread list
    unread_resp = client.get("/api/notifications?unread_only=true")
    assert unread_resp.status_code == 200
    unread_items = unread_resp.json()["notifications"]
    assert not any(item["id"] == n1["id"] for item in unread_items)

    # Mark all read
    all_read_resp = client.post("/api/notifications/read-all")
    assert all_read_resp.status_code == 200
    assert svc.get_unread_count() == 0

    # Channels endpoint
    chan_resp = client.get("/api/notifications/channels")
    assert chan_resp.status_code == 200
    channels = chan_resp.json()["channels"]
    channel_names = [c["channel"] for c in channels]
    assert "in_app" in channel_names
    assert "sms" in channel_names
    assert "email" in channel_names
    assert "telephony" in channel_names
    in_app_chan = next(c for c in channels if c["channel"] == "in_app")
    assert in_app_chan["status"] == "ACTIVE"


def test_escalation_callback_reschedule_workflow(test_app):
    from uuid import uuid4
    case_svc = test_app.state.case_service
    cb_svc = test_app.state.callback_service
    sess_id = f"SESS-{uuid4().hex[:8]}"
    cust_ref = f"CUST-{uuid4().hex[:8]}"

    # 1. Create support case
    case = case_svc.create_case(
        session_id=sess_id,
        customer_ref=cust_ref,
        issue_code="COMPLAINT",
        summary="Customer complaint about service",
    )
    assert case["case_id"].startswith("CASE-")
    assert case["priority"] == "High"

    # 2. Schedule callback linked to case
    from kural.services.callback_service import CallbackDraft
    now_utc = datetime.now(timezone.utc)
    scheduled_utc = now_utc.replace(microsecond=0)
    draft = CallbackDraft(
        scheduled_at_utc=scheduled_utc,
        scheduled_at_local="Tomorrow 11:00 AM",
        raw_expression="tomorrow morning",
        case_id=case["case_id"],
    )
    cb = cb_svc.upsert_callback(
        session_id=sess_id,
        customer_ref=cust_ref,
        draft=draft,
    )
    assert cb["callback_id"].startswith("CB-")
    assert cb["version"] == 1
    assert cb["status"] == "SCHEDULED"

    # 3. Reschedule callback (updates version and emits event)
    new_scheduled_utc = scheduled_utc
    rescheduled = cb_svc.reschedule_callback(
        callback_id=cb["callback_id"],
        scheduled_at_utc=new_scheduled_utc,
        scheduled_at_local="Tomorrow 3:00 PM",
        actor="STAFF",
    )
    assert rescheduled["version"] == 2
    assert rescheduled["scheduled_at_local"] == "Tomorrow 3:00 PM"

    # 4. Cancel callback
    cancelled = cb_svc.cancel_callback(callback_id=cb["callback_id"], actor="CUSTOMER")
    assert cancelled["status"] == "CANCELLED"
