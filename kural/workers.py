"""Background automation: outbox dispatch, notification delivery, SLA monitoring, callback
execution and campaign dialing.

Each ``*_tick`` is a deterministic, synchronous-or-async unit of work that tests call
directly. ``WorkerRunner`` loops them in the API process (development) or in a dedicated
process (``python -m kural.workers``, production). All claims are leased in the database,
so several workers and restarts never double-dial or double-notify.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from kural.config import get_settings
from kural.notifications.service import NotificationService
from kural.persistence.database import Database
from kural.persistence.models import CaseRow
from kural.policy.calling_policy import evaluate_contact_time
from kural.services.call_service import CallService
from kural.services.callback_service import CallbackService
from kural.services.campaign_service import CampaignService, SystemSettings
from kural.services.domain_events import emit_event
from kural.services.outbox_processor import OutboxProcessor
from kural.telephony.contracts import TelephonyCallRequest, TelephonyCallStatus

logger = logging.getLogger("kural.workers")
OPEN_CASES = ("NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER")


def outbox_tick(db: Database, notifications: NotificationService, batch: int = 25) -> int:
    """Route committed domain events into notifications (idempotent per event+recipient)."""
    processor = OutboxProcessor(db)
    handled = 0
    for event in processor.claim_batch(batch_size=batch):
        if processor.dispatch_single_event(event, custom_handler=lambda ev: notifications.route_event(ev) >= 0):
            handled += 1
    return handled


def sla_tick(db: Database, now: datetime | None = None) -> int:
    """Emit one SLA-warning and one SLA-breach event per open case, never more."""
    now = now or datetime.now(timezone.utc)
    fraction = get_settings().sla_warning_fraction
    emitted = 0
    with db.session() as s:
        with s.begin():
            rows = s.scalars(select(CaseRow).where(CaseRow.status.in_(OPEN_CASES), CaseRow.sla_due_at.is_not(None))
                             .with_for_update(skip_locked=True)).all()
            for c in rows:
                payload = {"case_id": c.case_id, "priority": c.priority, "status": c.status,
                           "sla_due_at": c.sla_due_at.isoformat(), "assigned_agent_id": c.assigned_agent_id}
                if c.sla_due_at <= now and c.sla_breached_at is None:
                    c.sla_breached_at = now
                    emit_event(s, "case.sla_breached", "CASE", c.case_id, payload, idempotency_key=f"case.sla_breached:{c.case_id}")
                    emitted += 1
                elif c.sla_warning_sent_at is None and c.sla_due_at > now:
                    total = (c.sla_due_at - c.created_at).total_seconds()
                    if total > 0 and (now - c.created_at).total_seconds() >= fraction * total:
                        c.sla_warning_sent_at = now
                        emit_event(s, "case.sla_warning", "CASE", c.case_id, payload, idempotency_key=f"case.sla_warning:{c.case_id}")
                        emitted += 1
    return emitted


def _caller_id(provider: Any) -> str:
    return getattr(provider, "caller_id", "") or ""


async def callback_tick(db: Database, telephony: Any, now: datetime | None = None) -> dict[str, int]:
    """Execute due callbacks: dial when every gate passes, otherwise hand to a human (DUE)."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    cb_svc, call_svc = CallbackService(db), CallService(db)
    stopped = SystemSettings(db).is_dialing_stopped()
    stats = {"dialed": 0, "handed_to_human": 0, "reconciled": 0}
    for job in cb_svc.claim_due(now=now):
        cid, version = job["callback_id"], job["version"]
        if job["recovered"] and job["provider_call_sid"]:
            # A previous worker started this dial and then lost its lease: reconcile, never re-dial blindly.
            status = await telephony.get_call_status(job["provider_call_sid"])
            terminal = {TelephonyCallStatus.COMPLETED, TelephonyCallStatus.BUSY, TelephonyCallStatus.NO_ANSWER,
                        TelephonyCallStatus.FAILED, TelephonyCallStatus.CANCELLED}
            if status.success and status.status in terminal:
                cb_svc.record_outcome(cid, outcome=status.status.value, provider_call_sid=job["provider_call_sid"],
                                      actor="RECONCILER")
            else:
                cb_svc.mark_dispatch_blocked(cid, version, code="RECONCILE_UNKNOWN",
                                             message="Previous dial outcome could not be confirmed; a human must verify before calling again.")
            stats["reconciled"] += 1
            continue
        gates = [
            (settings.outbound_autodial_enabled, "AUTODIAL_DISABLED", "Automated callback dialing is disabled (KURAL_OUTBOUND_AUTODIAL_ENABLED=false)."),
            (not stopped, "EMERGENCY_STOP", "Outbound dialing emergency stop is active."),
            (bool(telephony and telephony.is_configured), "TELEPHONY_NOT_CONFIGURED", "No telephony provider is configured."),
            (job["customer_exists"] and bool(job["phone"]), "NO_CUSTOMER_PHONE", "Customer record or phone number is missing."),
            (not job["dnd"], "CUSTOMER_DND", "Customer is on DND / opted out; only a human may decide to call."),
        ]
        window = evaluate_contact_time(now, now)
        gates.append((bool(window), window.code, window.message))
        if job["phone"]:
            gates.append((settings.is_dial_allowed(job["phone"]), "NOT_ALLOWLISTED",
                          "Number is not on the TELEPHONY_DIAL_ALLOWLIST for this environment."))
        blocked = next(((code, msg) for ok, code, msg in gates if not ok), None)
        if blocked:
            cb_svc.mark_dispatch_blocked(cid, version, code=blocked[0], message=blocked[1])
            stats["handed_to_human"] += 1
            continue
        call_id = f"CBC-{cid}-{version}"
        result = await telephony.initiate_call(TelephonyCallRequest(
            to_phone=job["phone"], from_phone=_caller_id(telephony), customer_ref=job["customer_ref"],
            call_id=call_id, callback_id=cid, idempotency_key=f"{cid}:v{version}",
        ))
        if not result.success:
            cb_svc.mark_dispatch_blocked(cid, version, code=result.error_code or "PROVIDER_ERROR",
                                         message=f"Provider rejected the call: {result.message}"[:400])
            with db.session() as s:
                with s.begin():
                    emit_event(s, "call.failed", "CALLBACK", cid, {"call_id": call_id, "customer_ref": job["customer_ref"],
                                                                   "reason": result.error_code or "PROVIDER_ERROR"})
            stats["handed_to_human"] += 1
            continue
        call_svc.create_call_record(session_id=call_id, customer_ref=job["customer_ref"], channel="PSTN",
                                    call_id=call_id, provider_call_sid=result.provider_call_sid, status="DIALING")
        cb_svc.record_dial_started(cid, version, provider_call_sid=result.provider_call_sid, call_record_id=call_id)
        stats["dialed"] += 1
    return stats


async def campaign_tick(db: Database, telephony: Any, now: datetime | None = None) -> int:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    if not (telephony and telephony.is_configured) or SystemSettings(db).is_dialing_stopped():
        return 0
    if not evaluate_contact_time(now, now):
        return 0
    camp_svc, call_svc = CampaignService(db), CallService(db)
    dialed = 0
    for camp in camp_svc.list_campaigns(status="ACTIVE"):
        for contact in camp_svc.claim_contacts_for_dialing(camp["id"], limit=camp.get("maxConcurrent") or 2):
            call_id = f"CMP-{contact['contact_id']}-{contact['attempts_count'] + 1}"
            result = await telephony.initiate_call(TelephonyCallRequest(
                to_phone=contact["phone"], from_phone=_caller_id(telephony), customer_ref=contact["customer_ref"],
                call_id=call_id, campaign_id=camp["id"], idempotency_key=call_id,
                custom_data={"contact_id": contact["contact_id"]},
            ))
            if result.success:
                call_svc.create_call_record(session_id=call_id, customer_ref=contact["customer_ref"], campaign_id=camp["id"],
                                            channel="PSTN", call_id=call_id, provider_call_sid=result.provider_call_sid,
                                            status="DIALING")
                camp_svc.mark_dial_started(contact["contact_id"], provider_call_sid=result.provider_call_sid, call_record_id=call_id)
                dialed += 1
            else:
                camp_svc.record_attempt(contact["contact_id"], "FAILED", call_id)
                logger.warning("Campaign dial failed campaign=%s contact=%s code=%s", camp["id"], contact["contact_id"], result.error_code)
    return dialed


class WorkerRunner:
    def __init__(self, db: Database, notifications: NotificationService, telephony_getter, interval_sec: float = 5.0) -> None:
        self.db, self.notifications, self.telephony_getter, self.interval = db, notifications, telephony_getter, interval_sec
        self._stop = asyncio.Event()
        self.last_tick: dict[str, str] = {}
        self.last_error: str | None = None

    async def run(self) -> None:
        logger.info("Background workers started (interval %.1fs)", self.interval)
        while not self._stop.is_set():
            for name, fn in (("outbox", lambda: outbox_tick(self.db, self.notifications)),
                             ("deliveries", lambda: self.notifications.process_deliveries()),
                             ("sla", lambda: sla_tick(self.db))):
                try:
                    await asyncio.to_thread(fn)
                    self.last_tick[name] = datetime.now(timezone.utc).isoformat()
                except Exception as exc:  # keep the loop alive; surface via /api/system/health
                    self.last_error = f"{name}: {type(exc).__name__}"
                    logger.warning("Worker %s failed: %s", name, type(exc).__name__)
            for name, coro in (("callbacks", callback_tick), ("campaigns", campaign_tick)):
                try:
                    await coro(self.db, self.telephony_getter())
                    self.last_tick[name] = datetime.now(timezone.utc).isoformat()
                except Exception as exc:
                    self.last_error = f"{name}: {type(exc).__name__}"
                    logger.warning("Worker %s failed: %s", name, type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO)
    from kural.config import validate_startup
    from kural.telephony.config import get_telephony_provider

    problems = validate_startup(get_settings())
    if problems:
        raise SystemExit("Refusing to start workers: " + " | ".join(problems))
    db = Database()
    db.prepare_schema(auto_migrate=get_settings().auto_migrate)
    asyncio.run(WorkerRunner(db, NotificationService(db), get_telephony_provider).run())


if __name__ == "__main__":  # pragma: no cover
    main()
