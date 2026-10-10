"""Durable notification domain service.

* In-app notifications are persisted per recipient user (so read state is personal).
* Every routed domain event also produces ``notification_deliveries`` rows for e-mail and
  SMS. A row is ``QUEUED`` when its channel is configured and the recipient has an
  address, otherwise ``NOT_CONFIGURED`` / ``SKIPPED`` with the reason recorded — so the
  delivery log never implies a message was sent when it was not.
* ``process_deliveries`` sends queued rows with leasing, bounded retries and exponential
  backoff; it is safe to run in several workers and after restarts.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kural.notifications.channels import DeliveryError, Transport, default_transports
from kural.persistence.database import Database
from kural.persistence.models import (
    AgentRow, CustomerRow, NotificationDeliveryRow, NotificationRow, UserRow, utcnow,
)
from kural.privacy.masking import mask_email, mask_phone

logger = logging.getLogger("kural.notifications")

DELIVERY_LEASE = timedelta(seconds=60)
SUPERVISORY_ROLES = ("SUPERVISOR", "OPS_MANAGER")


class NotificationService:
    def __init__(self, database: Database, transports: Optional[Dict[str, Transport]] = None) -> None:
        self.database = database
        self.transports = transports if transports is not None else default_transports()

    # ------------------------------------------------------------------ in-app
    def create_notification(
        self,
        title: str,
        message: str,
        level: str = "INFO",
        category: str = "SYSTEM",
        recipient_role: Optional[str] = None,
        user_id: Optional[str] = None,
        link_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.database.session() as s:
            row = self._add_in_app(s, title, message, level, category, recipient_role, user_id, link_url)
            s.commit()
            return self._serialize(row)

    @staticmethod
    def _add_in_app(s: Session, title: str, message: str, level: str, category: str,
                    recipient_role: Optional[str], user_id: Optional[str], link_url: Optional[str]) -> NotificationRow:
        row = NotificationRow(
            id=f"NOTIF-{uuid4().hex[:10].upper()}", recipient_role=recipient_role, user_id=user_id,
            title=title[:128], message=message, level=level.upper(), category=category.upper(),
            link_url=link_url, is_read=False, created_at=utcnow(), read_at=None,
        )
        s.add(row)
        return row

    @staticmethod
    def _visibility(q, recipient_role: Optional[str], user_id: Optional[str]):
        if user_id:
            return q.where(or_(
                NotificationRow.user_id == user_id,
                (NotificationRow.user_id.is_(None)) & (
                    NotificationRow.recipient_role.is_(None) | (NotificationRow.recipient_role == recipient_role)
                ),
            ))
        if recipient_role:
            return q.where(NotificationRow.recipient_role.is_(None) | (NotificationRow.recipient_role == recipient_role))
        return q

    def list_notifications(self, limit: int = 50, unread_only: bool = False,
                           recipient_role: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.database.session() as s:
            q = self._visibility(select(NotificationRow), recipient_role, user_id)
            if unread_only:
                q = q.where(NotificationRow.is_read.is_(False))
            rows = s.scalars(q.order_by(NotificationRow.created_at.desc()).limit(limit)).all()
            return [self._serialize(r) for r in rows]

    def get_unread_count(self, recipient_role: Optional[str] = None, user_id: Optional[str] = None) -> int:
        with self.database.session() as s:
            q = self._visibility(select(func.count(NotificationRow.id)), recipient_role, user_id)
            return s.scalar(q.where(NotificationRow.is_read.is_(False))) or 0

    def mark_as_read(self, notification_id: str, user_id: Optional[str] = None,
                     recipient_role: Optional[str] = None) -> bool:
        with self.database.session() as s:
            row = s.get(NotificationRow, notification_id)
            if not row:
                return False
            if user_id and row.user_id not in (None, user_id):
                return False
            if row.user_id is None and row.recipient_role not in (None, recipient_role) and recipient_role:
                return False
            row.is_read = True
            row.read_at = utcnow()
            s.commit()
            return True

    def mark_all_read(self, recipient_role: Optional[str] = None, user_id: Optional[str] = None) -> int:
        with self.database.session() as s:
            ids = s.scalars(self._visibility(select(NotificationRow.id), recipient_role, user_id)
                            .where(NotificationRow.is_read.is_(False))).all()
            if not ids:
                return 0
            res = s.execute(update(NotificationRow).where(NotificationRow.id.in_(ids)).values(is_read=True, read_at=utcnow()))
            s.commit()
            return res.rowcount

    # ------------------------------------------------------------------ routing
    def route_event(self, event: Dict[str, Any]) -> int:
        """Turn one committed domain event into in-app notifications and delivery rows.

        Idempotent per (event id, recipient, channel): re-processing a replayed event never
        duplicates notifications. Returns the number of recipients notified.
        """
        plan = build_notification_plan(event)
        if plan is None:
            return 0
        with self.database.session() as s:
            recipients = self._resolve_recipients(s, plan)
            if not recipients:
                logger.info("Notification event %s had no active recipients", event.get("event_type"))
                return 0
            count = 0
            for user in recipients:
                key_base = f"{event['id']}:{user['user_id']}"
                if s.scalar(select(NotificationDeliveryRow.id).where(
                        NotificationDeliveryRow.idempotency_key == f"{key_base}:IN_APP")) is not None:
                    continue
                notif = self._add_in_app(s, plan["title"], plan["message"], plan["level"], plan["category"],
                                         user["role"], user["user_id"], plan.get("link"))
                s.flush()
                s.add(self._delivery(event, notif.id, "IN_APP", user["label"], None, plan, f"{key_base}:IN_APP",
                                     status="DELIVERED", note="Stored in the recipient's in-app inbox"))
                for channel in plan["channels"]:
                    address = user.get("email") if channel == "EMAIL" else user.get("phone")
                    transport = self.transports.get(channel)
                    if transport is None or not transport.configured:
                        status, note = "NOT_CONFIGURED", f"{channel.title()} transport is not configured"
                    elif not address:
                        status, note = "SKIPPED", f"Recipient has no {'e-mail address' if channel == 'EMAIL' else 'mobile number'} on file"
                    else:
                        status, note = "QUEUED", None
                    s.add(self._delivery(event, notif.id, channel, user["label"], address, plan,
                                         f"{key_base}:{channel}", status=status, note=note))
                count += 1
            customer_sms = plan.get("customer_sms")
            if customer_sms and os.getenv("KURAL_CUSTOMER_SMS_ENABLED", "false").lower() == "true":
                customer = s.get(CustomerRow, customer_sms["customer_ref"])
                transport = self.transports.get("SMS")
                key = f"{event['id']}:customer:SMS"
                if customer and not customer.dnd_status and s.scalar(select(NotificationDeliveryRow.id).where(
                        NotificationDeliveryRow.idempotency_key == key)) is None:
                    status = "QUEUED" if transport and transport.configured else "NOT_CONFIGURED"
                    s.add(self._delivery(event, None, "SMS", f"Customer {customer.customer_ref}", customer.phone,
                                         {**plan, "title": "Callback confirmation", "message": customer_sms["text"]},
                                         key, status=status,
                                         note=None if status == "QUEUED" else "SMS transport is not configured"))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                return 0
            return count

    @staticmethod
    def _delivery(event: Dict[str, Any], notification_id: Optional[str], channel: str, label: str,
                  address: Optional[str], plan: Dict[str, Any], key: str, *, status: str,
                  note: Optional[str]) -> NotificationDeliveryRow:
        now = utcnow()
        return NotificationDeliveryRow(
            id=f"DLV-{uuid4().hex[:12].upper()}", notification_id=notification_id, source_event_id=event.get("id"),
            event_type=event.get("event_type", "unknown"), channel=channel, recipient_label=label[:128],
            recipient_address=address, subject=plan["title"][:200], body=plan["message"], status=status,
            attempts=0, max_attempts=int(os.getenv("KURAL_NOTIFY_MAX_ATTEMPTS", "5")),
            next_attempt_at=now if status == "QUEUED" else None, last_error=note, idempotency_key=key,
            created_at=now, updated_at=now, delivered_at=now if status == "DELIVERED" else None,
        )

    @staticmethod
    def _resolve_recipients(s: Session, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        users: dict[str, Dict[str, Any]] = {}

        def add(u: UserRow, agent: Optional[AgentRow] = None) -> None:
            if not u.is_active:
                return
            users[u.id] = {
                "user_id": u.id, "role": u.role, "label": f"{u.full_name} ({u.role})",
                "email": (agent.email if agent and agent.email else None) or u.email,
                "phone": (agent.phone if agent and agent.phone else None) or u.phone,
            }

        for agent_id in plan.get("agent_ids", []):
            if not agent_id:
                continue
            agent = s.get(AgentRow, agent_id)
            if agent and agent.user_id:
                user = s.get(UserRow, agent.user_id)
                if user:
                    add(user, agent)
        roles = plan.get("roles", [])
        if roles:
            for u in s.scalars(select(UserRow).where(UserRow.role.in_(roles), UserRow.is_active.is_(True))).all():
                add(u)
        return list(users.values())

    # ------------------------------------------------------------------ delivery
    def process_deliveries(self, limit: int = 20, now: Optional[datetime] = None) -> Dict[str, int]:
        now = now or utcnow()
        stats = {"sent": 0, "failed": 0, "retry": 0}
        with self.database.session() as s:
            with s.begin():
                rows = s.scalars(
                    select(NotificationDeliveryRow).where(
                        NotificationDeliveryRow.status.in_(("QUEUED", "SENDING")),
                        NotificationDeliveryRow.next_attempt_at <= now,
                        or_(NotificationDeliveryRow.locked_until.is_(None), NotificationDeliveryRow.locked_until <= now),
                    ).order_by(NotificationDeliveryRow.next_attempt_at.asc()).limit(limit).with_for_update(skip_locked=True)
                ).all()
                claimed = []
                for row in rows:
                    row.status = "SENDING"
                    row.locked_until = now + DELIVERY_LEASE
                    claimed.append((row.id, row.channel, row.recipient_address, row.subject, row.body))
        for delivery_id, channel, address, subject, body in claimed:
            transport = self.transports.get(channel)
            try:
                if transport is None:
                    raise DeliveryError(f"No transport for {channel}", permanent=True)
                provider_id = transport.send(address or "", subject, body)
                self._finish(delivery_id, ok=True, provider_id=provider_id)
                stats["sent"] += 1
            except DeliveryError as exc:
                final = self._finish(delivery_id, ok=False, error=str(exc), permanent=exc.permanent)
                stats["failed" if final else "retry"] += 1
            except Exception as exc:  # defensive: transport bug must not kill the worker
                final = self._finish(delivery_id, ok=False, error=f"Unexpected {type(exc).__name__}")
                stats["failed" if final else "retry"] += 1
        return stats

    def _finish(self, delivery_id: str, *, ok: bool, provider_id: Optional[str] = None,
                error: Optional[str] = None, permanent: bool = False) -> bool:
        now = utcnow()
        with self.database.session() as s:
            row = s.get(NotificationDeliveryRow, delivery_id)
            if row is None:
                return True
            row.attempts += 1
            row.locked_until = None
            row.updated_at = now
            if ok:
                row.status = "SENT"
                row.provider_message_id = provider_id
                row.delivered_at = now
                row.last_error = None
                s.commit()
                return True
            row.last_error = (error or "delivery failed")[:500]
            if permanent or row.attempts >= row.max_attempts:
                row.status = "FAILED"
                row.next_attempt_at = None
                s.commit()
                logger.warning("Notification delivery %s failed permanently (%s)", delivery_id, row.channel)
                return True
            row.status = "QUEUED"
            row.next_attempt_at = now + timedelta(seconds=min(3600, 30 * (2 ** (row.attempts - 1))))
            s.commit()
            return False

    def retry_delivery(self, delivery_id: str) -> Dict[str, Any]:
        with self.database.session() as s:
            row = s.get(NotificationDeliveryRow, delivery_id)
            if row is None:
                raise KeyError(delivery_id)
            if row.status not in ("FAILED",):
                raise ValueError("Only failed deliveries can be retried")
            transport = self.transports.get(row.channel)
            if transport is None or not transport.configured:
                raise ValueError(f"{row.channel.title()} transport is not configured")
            row.status = "QUEUED"
            row.attempts = 0
            row.next_attempt_at = utcnow()
            row.last_error = None
            s.commit()
            return self._serialize_delivery(row)

    def list_deliveries(self, limit: int = 100, status: Optional[str] = None,
                        channel: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.database.session() as s:
            q = select(NotificationDeliveryRow).order_by(NotificationDeliveryRow.created_at.desc()).limit(limit)
            if status:
                q = q.where(NotificationDeliveryRow.status == status.upper())
            if channel:
                q = q.where(NotificationDeliveryRow.channel == channel.upper())
            return [self._serialize_delivery(r) for r in s.scalars(q).all()]

    def delivery_summary(self) -> Dict[str, Dict[str, int]]:
        with self.database.session() as s:
            rows = s.execute(select(NotificationDeliveryRow.channel, NotificationDeliveryRow.status,
                                    func.count(NotificationDeliveryRow.id))
                             .group_by(NotificationDeliveryRow.channel, NotificationDeliveryRow.status)).all()
        summary: Dict[str, Dict[str, int]] = {}
        for channel, status, count in rows:
            summary.setdefault(channel, {})[status] = count
        return summary

    def get_channel_statuses(self) -> List[Dict[str, Any]]:
        """Truthfully reports availability of every delivery channel."""
        from kural.telephony.config import get_telephony_provider

        telephony = get_telephony_provider()
        email = self.transports.get("EMAIL")
        sms = self.transports.get("SMS")
        email_ok = bool(email and email.configured)
        sms_ok = bool(sms and sms.configured)
        return [
            {"channel": "in_app", "label": "In-app inbox", "status": "ACTIVE", "is_active": True,
             "description": "Notifications are stored per recipient and shown in the operations console."},
            {"channel": "email", "label": "Staff e-mail", "status": "CONFIGURED" if email_ok else "NOT_CONFIGURED",
             "is_active": email_ok, "description": email.describe() if email else "No e-mail transport"},
            {"channel": "sms", "label": "SMS (DLT gateway)", "status": "CONFIGURED" if sms_ok else "NOT_CONFIGURED",
             "is_active": sms_ok, "description": sms.describe() if sms else "No SMS transport"},
            {"channel": "telephony", "label": f"Telephony ({telephony.provider_name})",
             "status": "CONFIGURED" if telephony.is_configured else "NOT_CONFIGURED",
             "is_active": telephony.is_configured,
             "description": ("Outbound calling adapter configured; see Integrations for live health."
                             if telephony.is_configured else "No telephony provider configured. Set TELEPHONY_PROVIDER and credentials.")},
        ]

    @staticmethod
    def _serialize(row: NotificationRow) -> Dict[str, Any]:
        return {
            "id": row.id, "recipient_role": row.recipient_role, "user_id": row.user_id, "title": row.title,
            "message": row.message, "level": row.level, "category": row.category, "link_url": row.link_url,
            "is_read": row.is_read, "created_at": row.created_at.isoformat() if row.created_at else None,
            "read_at": row.read_at.isoformat() if row.read_at else None,
        }

    @staticmethod
    def _serialize_delivery(row: NotificationDeliveryRow) -> Dict[str, Any]:
        address = row.recipient_address or ""
        masked = mask_email(address) if "@" in address else (mask_phone(address) if address else "")
        return {
            "id": row.id, "notification_id": row.notification_id, "source_event_id": row.source_event_id,
            "event_type": row.event_type, "channel": row.channel, "recipient": row.recipient_label,
            "address": masked, "subject": row.subject, "status": row.status, "attempts": row.attempts,
            "max_attempts": row.max_attempts, "last_error": row.last_error,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "provider_message_id": row.provider_message_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        }


def _p(event: Dict[str, Any]) -> Dict[str, Any]:
    return event.get("payload") or {}


def build_notification_plan(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a domain event onto recipients, channels and customer-safe wording (no raw PII)."""
    et = event.get("event_type", "")
    p = _p(event)
    case_link = f"/work?case={p.get('case_id')}" if p.get("case_id") else "/work"
    cb_link = f"/work?tab=callbacks&callback={p.get('callback_id')}" if p.get("callback_id") else "/work?tab=callbacks"
    urgent = str(p.get("priority", "")).lower() in ("urgent", "high")
    if et == "case.created":
        unassigned = True  # the assignment event (if any) notifies the owner separately
        return {"title": f"New {p.get('priority', '')} case {p.get('case_id')}".replace("  ", " "),
                "message": f"{p.get('issue_code')} raised for customer {p.get('customer_ref')} "
                           f"(team {p.get('assigned_team')}). SLA due {p.get('sla_due_at')}.",
                "level": "WARNING" if urgent else "INFO", "category": "ESCALATION", "link": case_link,
                "roles": list(SUPERVISORY_ROLES) if unassigned else [], "agent_ids": [],
                "channels": ["EMAIL", "SMS"] if str(p.get("priority")).lower() == "urgent" else ["EMAIL"]}
    if et in ("case.assigned", "case.reassigned"):
        return {"title": f"Case {p.get('case_id')} assigned to you",
                "message": f"{p.get('issue_code')} · priority {p.get('priority')}. Open the Work Queue to respond.",
                "level": "WARNING" if urgent else "INFO", "category": "ESCALATION", "link": case_link,
                "roles": [], "agent_ids": [p.get("assigned_agent_id")],
                "channels": ["EMAIL", "SMS"] if urgent else ["EMAIL"]}
    if et == "case.sla_warning":
        return {"title": f"SLA at risk: case {p.get('case_id')}",
                "message": f"Case {p.get('case_id')} ({p.get('priority')}) is due {p.get('sla_due_at')} and is still {p.get('status')}.",
                "level": "WARNING", "category": "SLA", "link": case_link,
                "roles": ["SUPERVISOR"], "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL"]}
    if et == "case.sla_breached":
        return {"title": f"SLA breached: case {p.get('case_id')}",
                "message": f"Case {p.get('case_id')} ({p.get('priority')}) passed its SLA at {p.get('sla_due_at')}.",
                "level": "ERROR", "category": "SLA", "link": case_link,
                "roles": list(SUPERVISORY_ROLES), "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL", "SMS"]}
    if et in ("callback.scheduled", "callback.rescheduled"):
        verb = "scheduled" if et == "callback.scheduled" else "rescheduled"
        plan = {"title": f"Callback {verb}: {p.get('scheduled_at_local')}",
                "message": f"Callback {p.get('callback_id')} for customer {p.get('customer_ref')} is {verb} for "
                           f"{p.get('scheduled_at_local')}" + (f" (was {p.get('previous')})." if p.get("previous") else "."),
                "level": "INFO", "category": "CALLBACK", "link": cb_link,
                "roles": [] if p.get("assigned_agent_id") else ["SUPERVISOR"],
                "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL"]}
        if p.get("scheduled_at_local"):
            bank = os.getenv("KURAL_BANK_NAME", "Town Bank")
            plan["customer_sms"] = {"customer_ref": p.get("customer_ref"),
                                    "text": f"{bank}: your requested callback is {verb} for {p.get('scheduled_at_local')}. "
                                            f"We will never ask for your OTP, PIN or password."}
        return plan
    if et == "callback.cancelled":
        return {"title": f"Callback {p.get('callback_id')} cancelled",
                "message": f"The callback for customer {p.get('customer_ref')} ({p.get('scheduled_at_local')}) was cancelled.",
                "level": "INFO", "category": "CALLBACK", "link": cb_link,
                "roles": [] if p.get("assigned_agent_id") else ["SUPERVISOR"],
                "agent_ids": [p.get("assigned_agent_id")], "channels": []}
    if et == "callback.assigned":
        return {"title": f"Callback {p.get('callback_id')} assigned to you",
                "message": f"Customer {p.get('customer_ref')} · {p.get('scheduled_at_local')}.",
                "level": "INFO", "category": "CALLBACK", "link": cb_link,
                "roles": [], "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL"]}
    if et == "callback.due":
        return {"title": f"Callback due now: {p.get('callback_id')}",
                "message": f"Call customer {p.get('customer_ref')} now. Automated dialing did not run: {p.get('block_reason')}",
                "level": "WARNING", "category": "CALLBACK", "link": cb_link,
                "roles": [] if p.get("assigned_agent_id") else list(SUPERVISORY_ROLES),
                "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL", "SMS"]}
    if et == "callback.outcome":
        if p.get("status") not in ("FAILED", "DUE"):
            return None
        return {"title": f"Callback {p.get('callback_id')} needs attention",
                "message": f"Last attempt outcome: {p.get('outcome')}. Status is now {p.get('status')}.",
                "level": "WARNING", "category": "CALLBACK", "link": cb_link,
                "roles": ["SUPERVISOR"], "agent_ids": [p.get("assigned_agent_id")], "channels": ["EMAIL"]}
    if et == "call.failed":
        return {"title": "Outbound call failed",
                "message": f"Call {p.get('call_id')} for customer {p.get('customer_ref')} failed: {p.get('reason')}.",
                "level": "ERROR", "category": "TELEPHONY", "link": "/calls",
                "roles": list(SUPERVISORY_ROLES), "agent_ids": [], "channels": []}
    if et == "integration.health_changed":
        return {"title": f"Integration {p.get('integration')} is {p.get('status')}",
                "message": str(p.get("detail") or ""), "level": "ERROR" if p.get("status") != "HEALTHY" else "SUCCESS",
                "category": "SYSTEM", "link": "/governance?tab=integrations",
                "roles": ["SYSTEM_ADMIN", "OPS_MANAGER"], "agent_ids": [], "channels": ["EMAIL"]}
    if et == "dialing.emergency_stop":
        state = "stopped" if p.get("stopped") else "resumed"
        return {"title": f"Outbound dialing {state}",
                "message": f"{p.get('actor')} {state} all automated outbound dialing. Reason: {p.get('reason') or '—'}",
                "level": "ERROR" if p.get("stopped") else "SUCCESS", "category": "SYSTEM", "link": "/campaigns",
                "roles": ["OPS_MANAGER", "SUPERVISOR", "COMPLIANCE_OFFICER"], "agent_ids": [], "channels": ["EMAIL"]}
    return None
