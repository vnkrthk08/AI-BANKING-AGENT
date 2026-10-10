"""FastAPI Telephony router: call control, status discovery, and authenticated webhooks."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from kural.security.deps import Principal, require

from kural.policy.calling_policy import is_within_calling_hours, is_sunday
from kural.persistence.database import Database
from kural.persistence.models import CallRecordRow, CustomerRow
from kural.privacy.masking import mask_phone
from kural.services.event_bus import event_bus
from kural.telephony.config import get_telephony_provider
from kural.telephony.contracts import TelephonyCallRequest, TelephonyCallStatus

logger = logging.getLogger("kural.telephony.router")
telephony_router = APIRouter(prefix="/api/v1/telephony", tags=["telephony"])




@telephony_router.get("/status")
async def get_telephony_status(_: Principal = Depends(require("system:read"))) -> Dict[str, Any]:
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
async def initiate_telephony_call(request: Request, principal: Principal = Depends(require("telephony:dial"))) -> Dict[str, Any]:
    """Initiates an outbound telephone call with calling policy validation."""
    data = await request.json()
    customer_ref = data.get("customer_ref")
    to_phone = None
    campaign_id = data.get("campaign_id")
    callback_id = data.get("callback_id")
    idempotency_key = data.get("idempotency_key") or f"dial_{uuid4().hex[:8]}"

    if not customer_ref:
        raise HTTPException(status_code=400, detail="customer_ref is required; numbers are dialled only from customer records")
    from kural.config import get_settings
    from kural.services.campaign_service import SystemSettings

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
            if cust is None:
                raise HTTPException(status_code=404, detail="Customer not found")
            to_phone = cust.phone
            if cust.dnd_status:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Policy violation: Customer {customer_ref} is registered on the National Do-Not-Disturb (DND) registry.",
                )

    if SystemSettings(db).is_dialing_stopped():
        raise HTTPException(status_code=423, detail="Outbound dialing is stopped (emergency stop active)")
    if not get_settings().is_dial_allowed(to_phone):
        raise HTTPException(status_code=403, detail="Number is not on this environment's TELEPHONY_DIAL_ALLOWLIST")
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

    # Record persistent call record (session row created alongside so history links up)
    from kural.services.call_service import CallService
    rec = CallService(db).create_call_record(
        session_id=call_id, customer_ref=customer_ref, campaign_id=campaign_id, channel="PSTN", call_id=call_id,
        provider_call_sid=result.provider_call_sid or None, status="DIALING" if result.success else "COMPLETED",
    )
    if not result.success:
        CallService(db).update_call_by_session(call_id, {"disposition": "FAILED", "connected": False})

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


TERMINAL = {"COMPLETED", "BUSY", "NO_ANSWER", "FAILED", "CANCELLED"}


def apply_telephony_event(db: Database, provider_name: str, event) -> dict[str, Any]:
    """Persist-then-apply one provider status event. Duplicate/replayed events are ignored and
    a late non-terminal event can never overwrite a terminal outcome."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from kural.persistence.models import TelephonyEventRow
    from kural.services.callback_service import CallbackService
    from kural.services.campaign_service import CampaignService

    status_value = event.status.value
    dedupe_key = f"{provider_name}:{event.provider_call_sid or event.call_id}:{status_value}"
    with db.session() as s:
        s.add(TelephonyEventRow(provider=provider_name, dedupe_key=dedupe_key[:200], provider_call_sid=event.provider_call_sid,
                                call_id=event.call_id or None, status=status_value))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return {"status": "ignored", "reason": "duplicate_event"}

    applied = []
    with db.session() as s:
        rec = None
        if event.provider_call_sid:
            rec = s.scalar(select(CallRecordRow).where(CallRecordRow.provider_call_sid == event.provider_call_sid))
        if rec is None and event.call_id:
            rec = s.get(CallRecordRow, event.call_id)
        if rec is not None:
            if rec.status in TERMINAL or rec.status == "COMPLETED" and rec.ended_at:
                pass  # terminal already; stale event
            elif status_value in TERMINAL:
                rec.status = "COMPLETED"
                rec.disposition = rec.disposition if rec.disposition not in (None, "INITIATED") else status_value
                rec.connected = status_value == "COMPLETED"
                rec.ended_at = datetime.now(timezone.utc)
                if event.duration_sec:
                    rec.duration_sec = int(event.duration_sec)
                applied.append("call_record")
            elif status_value == "IN_PROGRESS":
                rec.status, rec.connected = "IN_PROGRESS", True
                applied.append("call_record")
            s.commit()
    if status_value in TERMINAL and event.provider_call_sid:
        cb_svc = CallbackService(db)
        cb = cb_svc.find_by_provider_sid(event.provider_call_sid)
        if cb and cb_svc.record_outcome(cb["callback_id"], outcome=status_value, provider_call_sid=event.provider_call_sid):
            applied.append("callback")
        camp_svc = CampaignService(db)
        contact = camp_svc.find_contact_by_provider_sid(event.provider_call_sid)
        if contact and contact["status"] == "DIALING":
            camp_svc.record_attempt(contact["contact_id"], status_value, contact.get("last_session_id") or event.provider_call_sid)
            applied.append("campaign_contact")
    with db.session() as s:
        row = s.scalar(select(TelephonyEventRow).where(TelephonyEventRow.dedupe_key == dedupe_key[:200]))
        if row:
            row.applied = bool(applied)
            row.note = ",".join(applied) or "no matching record"
            s.commit()
    return {"status": "accepted", "applied": applied}


@telephony_router.post("/webhooks")
async def handle_telephony_webhook(request: Request) -> Dict[str, Any]:
    """Authenticated provider status callback (signature or shared token, fail-closed)."""
    import hmac as _hmac
    from kural.config import get_settings

    body_bytes = await request.body()
    headers_dict = {k: v for k, v in request.headers.items()}
    provider = get_telephony_provider()
    token = get_settings().telephony_webhook_token
    supplied = request.query_params.get("token") or request.headers.get("x-kural-webhook-token") or ""
    token_ok = bool(token) and _hmac.compare_digest(supplied, token)
    if not (token_ok or provider.verify_webhook_signature(body_bytes, headers_dict)):
        logger.warning("Rejected unauthenticated telephony webhook")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing telephony webhook signature")
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = json.loads(body_bytes.decode("utf-8"))
        else:
            from urllib.parse import parse_qs
            parsed = parse_qs(body_bytes.decode("utf-8"))
            payload = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unparseable webhook payload") from exc
    event = provider.parse_webhook_event(payload, headers_dict)
    db: Database = request.app.state.database
    result = apply_telephony_event(db, provider.provider_name, event)
    event_bus.publish("telephony_status_updated", {"call_id": event.call_id, "status": event.status.value})
    return {**result, "event_id": event.event_id}


@telephony_router.post("/calls/{call_id}/transfer")
async def transfer_telephony_call(call_id: str, request: Request, principal: Principal = Depends(require("telephony:transfer"))) -> Dict[str, Any]:
    """Live-bridges an active telephone call to a human banking representative."""
    data = await request.json()
    agent_id = data.get("agent_id")
    agent_phone = None

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
            if not rec.provider_call_sid:
                raise HTTPException(status_code=409, detail="Live transfer is only possible on PSTN calls placed through the telephony provider")
            provider_sid = rec.provider_call_sid
            from kural.persistence.models import AgentRow
            agent = s.get(AgentRow, agent_id)
            if agent is None or not agent.phone:
                raise HTTPException(status_code=409, detail="Agent has no transfer number on file")
            if agent.availability != "AVAILABLE":
                raise HTTPException(status_code=409, detail="Agent is not available")
            agent_phone = agent.phone

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
