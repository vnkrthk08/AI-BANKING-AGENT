"""FastAPI Telephony router: call control, status discovery, and authenticated webhooks."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from kural.policy.calling_policy import is_within_calling_hours, is_sunday
from kural.persistence.database import Database
from kural.persistence.models import CallRecordRow, CustomerRow
from kural.services.event_bus import event_bus
from kural.telephony.config import get_telephony_provider
from kural.telephony.contracts import TelephonyCallRequest, TelephonyCallStatus

logger = logging.getLogger("kural.telephony.router")
telephony_router = APIRouter(prefix="/api/v1/telephony", tags=["telephony"])

_PROCESSED_WEBHOOK_EVENT_IDS: set[str] = set()


@telephony_router.get("/status")
async def get_telephony_status() -> Dict[str, Any]:
    """Exposes truthful telephony provider configuration, live status, and capabilities."""
    provider = get_telephony_provider()
    health = await provider.health_check()
    return {
        "provider": health.provider_name,
        "status": health.status.value,
        "is_live": health.is_live,
        "caller_id": health.configured_phone_number,
        "last_health_check": health.last_health_check.isoformat() if health.last_health_check else None,
        "last_error": health.last_error,
        "details": health.details,
    }


@telephony_router.post("/calls")
async def initiate_telephony_call(request: Request) -> Dict[str, Any]:
    """Initiates an outbound telephone call with calling policy validation."""
    data = await request.json()
    to_phone = data.get("to_phone")
    customer_ref = data.get("customer_ref", "CUST-UNKNOWN")
    campaign_id = data.get("campaign_id")
    callback_id = data.get("callback_id")
    idempotency_key = data.get("idempotency_key") or f"dial_{uuid4().hex[:8]}"

    if not to_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="to_phone is required"
        )

    # 1. Telephony calling hours and holiday policy check (Spec §9 / RBI compliance)
    now_ist = datetime.now(timezone.utc)
    if is_sunday(now_ist):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Policy violation: Telephony calls are strictly prohibited on Sundays per bank regulatory policy.",
        )
    if not is_within_calling_hours(now_ist):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Policy violation: Telephony calls are only permitted within 09:00 - 19:00 IST.",
        )

    # 2. Check Customer DND status in database
    db: Database = getattr(request.app.state, "database", None)
    if db is not None:
        with db.session() as s:
            cust = s.get(CustomerRow, customer_ref)
            if cust is not None and cust.dnd_status:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Policy violation: Customer {customer_ref} is registered on the National Do-Not-Disturb (DND) registry.",
                )

    call_id = f"TEL-{uuid4().hex[:8].upper()}"
    provider = get_telephony_provider()

    call_req = TelephonyCallRequest(
        to_phone=to_phone,
        from_phone=getattr(provider, "caller_id", "+91 1800 200 4400"),
        customer_ref=customer_ref,
        call_id=call_id,
        campaign_id=campaign_id,
        callback_id=callback_id,
        idempotency_key=idempotency_key,
    )

    result = await provider.initiate_call(call_req)

    # Record persistent call record
    if db is not None:
        with db.session() as s:
            rec = CallRecordRow(
                call_id=call_id,
                session_id=call_id,
                customer_ref=customer_ref,
                campaign_id=campaign_id,
                callback_id=callback_id,
                masked_phone=to_phone[:6] + "XX" + to_phone[-2:] if len(to_phone) > 8 else "+91 98XXX XX000",
                status="IN_PROGRESS" if result.success else "FAILED",
                disposition="INITIATED" if result.success else "FAILED",
                resolution_mode="AI",
                connected=result.success,
                started_at=datetime.now(timezone.utc),
            )
            s.add(rec)
            s.commit()

    event_bus.publish("telephony_call_initiated", {
        "call_id": call_id,
        "provider_sid": result.provider_call_sid,
        "success": result.success,
    })

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.message or "Telephony gateway rejected call initiation",
        )

    return {
        "success": True,
        "call_id": call_id,
        "provider_call_sid": result.provider_call_sid,
        "status": result.status.value,
        "message": result.message,
    }


@telephony_router.post("/webhooks")
async def handle_telephony_webhook(request: Request) -> Dict[str, Any]:
    """Authenticates and processes status callbacks from the telephony provider."""
    body_bytes = await request.body()
    headers_dict = {k: v for k, v in request.headers.items()}
    provider = get_telephony_provider()

    # 1. Cryptographic HMAC webhook verification
    if not provider.verify_webhook_signature(body_bytes, headers_dict):
        logger.warning("Rejected unauthenticated telephony webhook from %s", request.client.host if request.client else "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing telephony webhook signature",
        )

    # 2. Parse body
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = json.loads(body_bytes.decode("utf-8"))
        else:
            # Handle standard application/x-www-form-urlencoded
            from urllib.parse import parse_qs
            parsed = parse_qs(body_bytes.decode("utf-8"))
            payload = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unparseable webhook payload") from exc

    event = provider.parse_webhook_event(payload, headers_dict)

    # 3. Deduplication and replay protection
    if event.event_id in _PROCESSED_WEBHOOK_EVENT_IDS:
        logger.info("Ignoring duplicate telephony webhook event %s", event.event_id)
        return {"status": "ignored", "reason": "duplicate_event"}

    _PROCESSED_WEBHOOK_EVENT_IDS.add(event.event_id)
    if len(_PROCESSED_WEBHOOK_EVENT_IDS) > 10000:
        _PROCESSED_WEBHOOK_EVENT_IDS.clear()

    # 4. Update database record atomically
    db: Database = getattr(request.app.state, "database", None)
    if db is not None and event.call_id:
        with db.session() as s:
            rec = s.get(CallRecordRow, event.call_id)
            if rec is not None:
                if event.status in (TelephonyCallStatus.COMPLETED, TelephonyCallStatus.FAILED, TelephonyCallStatus.BUSY, TelephonyCallStatus.NO_ANSWER):
                    rec.status = "COMPLETED"
                    rec.disposition = event.status.value
                    if event.duration_sec:
                        rec.duration_sec = event.duration_sec
                    if event.recording_url:
                        rec.recording_available = True
                        rec.recording_path = event.recording_url
                s.commit()

    event_bus.publish("telephony_status_updated", {
        "call_id": event.call_id,
        "provider_sid": event.provider_call_sid,
        "status": event.status.value,
        "duration": event.duration_sec,
    })

    return {"status": "accepted", "event_id": event.event_id}


@telephony_router.post("/calls/{call_id}/transfer")
async def transfer_telephony_call(call_id: str, request: Request) -> Dict[str, Any]:
    """Live-bridges an active telephone call to a human banking representative."""
    data = await request.json()
    agent_id = data.get("agent_id")
    agent_phone = data.get("agent_phone", "+91 98765 00001")

    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")

    provider = get_telephony_provider()
    db: Database = getattr(request.app.state, "database", None)
    provider_sid = ""

    if db is not None:
        with db.session() as s:
            rec = s.get(CallRecordRow, call_id)
            if not rec:
                raise HTTPException(status_code=404, detail="Call record not found")
            provider_sid = rec.session_id or call_id

    result = await provider.transfer_to_agent(
        provider_call_sid=provider_sid,
        agent_phone=agent_phone,
        agent_id=agent_id,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.message or "Agent bridging failed at telephony gateway",
        )

    # Update database resolution mode to HUMAN
    if db is not None:
        with db.session() as s:
            rec = s.get(CallRecordRow, call_id)
            if rec:
                rec.resolution_mode = "HUMAN"
                rec.summary = (rec.summary + f" [Transferred to agent {agent_id}]").strip()
                s.commit()

    return {
        "success": True,
        "call_id": call_id,
        "agent_id": agent_id,
        "status": result.status,
        "message": result.message,
    }
