"""Campaign domain service: campaign lifecycle, contact queue management, retry scheduling, and pacing stats."""

import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CampaignContactRow, CampaignRow, CustomerRow, SystemSettingRow
from kural.services.customer_service import normalize_indian_phone

DIALABLE_STATUSES = ("PENDING", "QUEUED", "RETRY_SCHEDULED")
CONNECTED_OUTCOMES = {"COMPLETED", "CLOSED", "CALLBACK_SCHEDULED", "ESCALATED", "NOT_INTERESTED"}
EDITABLE_FIELDS_RESET_APPROVAL = {"objective", "script_version", "scriptVersion", "languages", "region", "category",
                                  "max_attempts", "maxAttempts", "retry_gap_hours", "retryGapHours"}
DIALING_LEASE = timedelta(minutes=15)


class CampaignStateError(ValueError):
    """Requested campaign transition is not allowed in the current state."""


class SystemSettings:
    """Persisted operator controls shared by every API and worker process."""

    DIALING_KEY = "outbound_dialing"

    def __init__(self, database: Database) -> None:
        self.database = database

    def dialing_state(self) -> dict[str, Any]:
        with self.database.session() as s:
            row = s.get(SystemSettingRow, self.DIALING_KEY)
            value = dict(row.value_json) if row else {}
            return {
                "stopped": bool(value.get("stopped", False)),
                "reason": value.get("reason"),
                "actor": row.updated_by if row else None,
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            }

    def is_dialing_stopped(self) -> bool:
        return self.dialing_state()["stopped"]

    def set_dialing_stopped(self, stopped: bool, *, actor: str, reason: str | None = None) -> dict[str, Any]:
        from kural.services.domain_events import emit_event
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                row = s.get(SystemSettingRow, self.DIALING_KEY)
                if row is None:
                    row = SystemSettingRow(key=self.DIALING_KEY, value_json={})
                    s.add(row)
                row.value_json = {"stopped": stopped, "reason": reason}
                row.updated_by = actor
                row.updated_at = now
                if stopped:
                    # Release in-flight claims so nothing dials after the stop takes effect.
                    s.execute(update(CampaignContactRow).where(CampaignContactRow.status == "QUEUED")
                              .values(status="PENDING"))
                emit_event(s, "dialing.emergency_stop", "SYSTEM", self.DIALING_KEY,
                           {"stopped": stopped, "reason": reason, "actor": actor},
                           idempotency_key=f"dialing.emergency_stop:{stopped}:{now.timestamp()}")
        return self.dialing_state()


class CampaignService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_campaign(
        self,
        name: str,
        objective: str = "App adoption",
        script_version: str = "v1.0",
        segment_size: int = 0,
        max_attempts: int = 3,
        retry_gap_hours: int = 24,
        languages: list[str] | None = None,
        region: str = "All India",
        status: str = "DRAFT",
        category: str = "SERVICE",
        max_concurrent: int = 2,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        cid = f"CMP-{uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        row = CampaignRow(
            campaign_id=cid,
            name=name,
            objective=objective,
            status=status,
            script_version=script_version,
            segment_size=segment_size,
            max_attempts=max_attempts,
            retry_gap_hours=retry_gap_hours,
            languages_json=languages or ["Hindi", "English"],
            region=region,
            calls_dialed=0,
            answer_rate=0.0,
            category=(category or "SERVICE").upper(),
            max_concurrent=max(1, min(int(max_concurrent or 2), 20)),
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        with self.database.session() as s:
            s.add(row)
            s.commit()
            return self._serialize_campaign(row, s)

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            return self._serialize_campaign(row, s) if row else None

    def list_campaigns(self, status: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as s:
            query = select(CampaignRow)
            if status:
                query = query.where(CampaignRow.status == status)
            if region:
                query = query.where(CampaignRow.region == region)
            query = query.order_by(CampaignRow.created_at.desc())
            rows = s.scalars(query).all()
            return [self._serialize_campaign(r, s) for r in rows]

    def update_campaign(self, campaign_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            if not row:
                raise KeyError(f"Campaign not found: {campaign_id}")
            if "name" in patch:
                row.name = patch["name"]
            if "objective" in patch:
                row.objective = patch["objective"]
            if "status" in patch:
                row.status = patch["status"]
            if "script_version" in patch or "scriptVersion" in patch:
                row.script_version = patch.get("script_version") or patch.get("scriptVersion")
            if "segment_size" in patch or "segmentSize" in patch:
                row.segment_size = int(patch.get("segment_size") or patch.get("segmentSize"))
            if "max_attempts" in patch or "maxAttempts" in patch:
                row.max_attempts = int(patch.get("max_attempts") or patch.get("maxAttempts"))
            if "retry_gap_hours" in patch or "retryGapHours" in patch:
                row.retry_gap_hours = int(patch.get("retry_gap_hours") or patch.get("retryGapHours"))
            if "languages" in patch:
                row.languages_json = patch["languages"]
            if "region" in patch:
                row.region = patch["region"]
            if "category" in patch:
                row.category = str(patch["category"]).upper()
            if "max_concurrent" in patch or "maxConcurrent" in patch:
                row.max_concurrent = max(1, min(int(patch.get("max_concurrent") or patch.get("maxConcurrent")), 20))
            if EDITABLE_FIELDS_RESET_APPROVAL & set(patch) and row.approved_at is not None and row.status in ("DRAFT", "APPROVED", "PAUSED"):
                # Material change after approval: compliance must approve the new configuration.
                row.approved_at = None
                row.approved_by = None
                if row.status == "APPROVED":
                    row.status = "DRAFT"
            row.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_campaign(row, s)

    def start_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Low-level state change. Operator launches go through ``launch_campaign`` which enforces preflight."""
        return self.update_campaign(campaign_id, {"status": "ACTIVE"})

    def approve_campaign(self, campaign_id: str, *, actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            if not row:
                raise KeyError(campaign_id)
            if row.status not in ("DRAFT", "APPROVED"):
                raise CampaignStateError(f"Only draft campaigns can be approved (status {row.status})")
            if row.category.upper() != "SERVICE":
                raise CampaignStateError("Only SERVICE campaigns can be approved for automated calling; "
                                         "promotional calling requires separate legal sign-off")
            row.approved_by = actor
            row.approved_at = now
            row.status = "APPROVED"
            row.updated_at = now
            s.commit()
            return self._serialize_campaign(row, s)

    def preflight(self, campaign_id: str, *, telephony_configured: bool, telephony_healthy: bool | None,
                  dialing_stopped: bool) -> dict[str, Any]:
        """Evaluate every gate that must pass before automated dialing may begin."""
        from kural.config import get_settings
        from kural.policy.calling_policy import evaluate_contact_time

        settings = get_settings()
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            if not row:
                raise KeyError(campaign_id)
            contacts = s.scalars(select(CampaignContactRow).where(CampaignContactRow.campaign_id == campaign_id)).all()
            eligible = 0
            not_allowlisted = 0
            for c in contacts:
                if c.status not in DIALABLE_STATUSES:
                    continue
                cust = s.get(CustomerRow, c.customer_ref)
                if cust is not None and cust.dnd_status:
                    continue
                if not settings.is_dial_allowed(c.phone):
                    not_allowlisted += 1
                    continue
                eligible += 1
            checks = [
                {"key": "approval", "label": "Compliance approval", "ok": row.approved_at is not None,
                 "detail": f"Approved by {row.approved_by}" if row.approved_at else "A compliance officer must approve this campaign"},
                {"key": "category", "label": "Service (non-promotional) campaign", "ok": row.category == "SERVICE",
                 "detail": "Promotional calling is disabled pending legal sign-off" if row.category != "SERVICE" else "Service campaign"},
                {"key": "telephony", "label": "Telephony provider configured", "ok": telephony_configured,
                 "detail": "Configure TELEPHONY_PROVIDER and credentials" if not telephony_configured else "Provider configured"},
                {"key": "telephony_health", "label": "Telephony provider healthy", "ok": bool(telephony_healthy),
                 "detail": "Provider health check did not pass" if not telephony_healthy else "Health check passed"},
                {"key": "emergency_stop", "label": "Outbound dialing enabled", "ok": not dialing_stopped,
                 "detail": "Emergency stop is active" if dialing_stopped else "No emergency stop in effect"},
                {"key": "contacts", "label": "Eligible contacts", "ok": eligible > 0,
                 "detail": f"{eligible} eligible" + (f", {not_allowlisted} blocked by the test-number allowlist" if not_allowlisted else "")},
            ]
            window = evaluate_contact_time(datetime.now(timezone.utc))
            return {
                "campaign_id": campaign_id,
                "ready": all(c["ok"] for c in checks),
                "checks": checks,
                "eligible_contacts": eligible,
                "calling_window_open": bool(window),
                "calling_window_note": None if window else f"{window.message} Dialing will wait for the next permitted window.",
            }

    def launch_campaign(self, campaign_id: str, preflight: dict[str, Any]) -> dict[str, Any]:
        if not preflight["ready"]:
            failed = [c["label"] for c in preflight["checks"] if not c["ok"]]
            raise CampaignStateError("Campaign cannot start: " + "; ".join(failed))
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            if not row:
                raise KeyError(campaign_id)
            if row.status not in ("APPROVED", "PAUSED"):
                raise CampaignStateError(f"Campaign in status {row.status} cannot be started")
            row.status = "ACTIVE"
            row.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_campaign(row, s)

    def cancel_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            if not row:
                raise KeyError(campaign_id)
            if row.status in ("COMPLETED", "CANCELLED"):
                raise CampaignStateError(f"Campaign is already {row.status.lower()}")
            row.status = "CANCELLED"
            row.updated_at = datetime.now(timezone.utc)
            s.execute(update(CampaignContactRow).where(
                CampaignContactRow.campaign_id == campaign_id,
                CampaignContactRow.status.in_(DIALABLE_STATUSES),
            ).values(status="CANCELLED", next_attempt_at=None))
            s.commit()
            return self._serialize_campaign(row, s)

    def claim_contacts_for_dialing(self, campaign_id: str, limit: int) -> list[dict[str, Any]]:
        """Lease dialable contacts (DND scrubbed at claim time) and mark them DIALING."""
        from kural.config import get_settings
        settings = get_settings()
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            with s.begin():
                camp = s.get(CampaignRow, campaign_id)
                if camp is None or camp.status != "ACTIVE":
                    return []
                in_flight = s.scalar(select(func.count(CampaignContactRow.contact_id)).where(
                    CampaignContactRow.campaign_id == campaign_id, CampaignContactRow.status == "DIALING",
                    CampaignContactRow.next_attempt_at > now)) or 0
                capacity = max(0, min(limit, camp.max_concurrent - in_flight))
                if capacity == 0:
                    return []
                candidates = s.scalars(select(CampaignContactRow).where(
                    CampaignContactRow.campaign_id == campaign_id,
                    ((CampaignContactRow.status.in_(("PENDING", "QUEUED")))
                     | ((CampaignContactRow.status == "RETRY_SCHEDULED") & (CampaignContactRow.next_attempt_at <= now))
                     | ((CampaignContactRow.status == "DIALING") & (CampaignContactRow.next_attempt_at <= now))),
                ).order_by(CampaignContactRow.created_at.asc()).with_for_update(skip_locked=True)).all()
                claimed: list[dict[str, Any]] = []
                for c in candidates:
                    cust = s.get(CustomerRow, c.customer_ref)
                    if cust is not None and cust.dnd_status:
                        c.status = "DND_EXCLUDED"
                        c.next_attempt_at = None
                        continue
                    if not settings.is_dial_allowed(c.phone):
                        continue
                    c.status = "DIALING"
                    c.next_attempt_at = now + DIALING_LEASE  # lease expiry; reclaimed if no outcome arrives
                    c.last_attempt_at = now
                    claimed.append(self._serialize_contact(c))
                    if len(claimed) >= capacity:
                        break
                return claimed

    def mark_dial_started(self, contact_id: str, *, provider_call_sid: str, call_record_id: str) -> None:
        with self.database.session() as s:
            c = s.get(CampaignContactRow, contact_id)
            if c is None:
                return
            c.provider_call_sid = provider_call_sid
            c.call_record_id = call_record_id
            c.last_session_id = call_record_id
            s.commit()

    def find_contact_by_provider_sid(self, provider_call_sid: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            c = s.scalar(select(CampaignContactRow).where(CampaignContactRow.provider_call_sid == provider_call_sid))
            return self._serialize_contact(c) if c else None

    def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self.update_campaign(campaign_id, {"status": "PAUSED"})

    def complete_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self.update_campaign(campaign_id, {"status": "COMPLETED"})

    def add_contact(self, campaign_id: str, customer_ref: str, phone: str) -> dict[str, Any]:
        norm_phone = normalize_indian_phone(phone)
        now = datetime.now(timezone.utc)
        contact_id = f"CNT-{uuid4().hex[:8].upper()}"
        with self.database.session() as s:
            existing = s.scalar(
                select(CampaignContactRow).where(
                    CampaignContactRow.campaign_id == campaign_id,
                    CampaignContactRow.customer_ref == customer_ref,
                )
            )
            if existing is not None:
                return self._serialize_contact(existing)

            # Check if customer is DND
            cust = s.get(CustomerRow, customer_ref)
            initial_status = "DND_EXCLUDED" if (cust and cust.dnd_status) else "PENDING"

            row = CampaignContactRow(
                contact_id=contact_id,
                campaign_id=campaign_id,
                customer_ref=customer_ref,
                phone=norm_phone,
                status=initial_status,
                attempts_count=0,
                created_at=now,
                updated_at=now,
            )
            s.add(row)

            # Increment campaign segment size
            camp = s.get(CampaignRow, campaign_id)
            if camp:
                camp.segment_size += 1

            s.commit()
            return self._serialize_contact(row)

    def import_contacts_csv(self, campaign_id: str, csv_content: str) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(csv_content))
        added = 0
        skipped = 0
        errors: list[dict[str, Any]] = []

        for index, row in enumerate(reader, start=1):
            phone = row.get("phone") or row.get("mobile")
            cust_ref = row.get("customer_ref") or row.get("id") or f"CUST-IMP-{index:04d}"
            if not phone:
                skipped += 1
                errors.append({"row": index, "reason": "Missing phone number"})
                continue
            try:
                self.add_contact(campaign_id, cust_ref, phone)
                added += 1
            except Exception as e:
                skipped += 1
                errors.append({"row": index, "reason": str(e)})

        return {"campaign_id": campaign_id, "added": added, "skipped": skipped, "errors": errors}

    def list_contacts(self, campaign_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as s:
            q = select(CampaignContactRow).where(CampaignContactRow.campaign_id == campaign_id)
            if status:
                q = q.where(CampaignContactRow.status == status)
            q = q.limit(limit)
            return [self._serialize_contact(c) for c in s.scalars(q).all()]

    def get_queued_contacts(self, campaign_id: str, batch_size: int = 5) -> list[dict[str, Any]]:
        """Retrieves dialable contacts: PENDING, QUEUED, or RETRY_SCHEDULED where retry time has elapsed.
        Applies pre-dispatch DND scrubbing against Customer records before queueing.
        """
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            q = (
                select(CampaignContactRow)
                .where(
                    CampaignContactRow.campaign_id == campaign_id,
                    (CampaignContactRow.status.in_(["PENDING", "QUEUED"]))
                    | (
                        (CampaignContactRow.status == "RETRY_SCHEDULED")
                        & (CampaignContactRow.next_attempt_at <= now)
                    ),
                )
                .order_by(CampaignContactRow.created_at.asc())
            )
            candidates = s.scalars(q).all()
            dialable: list[CampaignContactRow] = []
            for r in candidates:
                cust = s.get(CustomerRow, r.customer_ref)
                if cust and cust.dnd_status:
                    r.status = "DND_EXCLUDED"
                    r.next_attempt_at = None
                else:
                    r.status = "QUEUED"
                    dialable.append(r)
                    if len(dialable) >= batch_size:
                        break
            s.commit()
            return [self._serialize_contact(r) for r in dialable]

    def record_attempt(
        self,
        contact_id: str,
        disposition: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Updates contact dial attempt, evaluates retry vs completion, and updates campaign stats."""
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            contact = s.get(CampaignContactRow, contact_id)
            if not contact:
                raise KeyError(f"Contact not found: {contact_id}")
            if contact.status in ("COMPLETED", "FAILED", "DND_EXCLUDED", "OPTED_OUT", "CANCELLED") and contact.last_session_id == session_id:
                return self._serialize_contact(contact)  # duplicate outcome for the same attempt

            campaign = s.get(CampaignRow, contact.campaign_id)
            max_attempts = campaign.max_attempts if campaign else 3
            retry_gap = campaign.retry_gap_hours if campaign else 24

            contact.attempts_count += 1
            contact.last_attempt_at = now
            contact.last_disposition = disposition
            contact.last_session_id = session_id

            if disposition in CONNECTED_OUTCOMES:
                contact.status = "COMPLETED"
                contact.next_attempt_at = None
            elif disposition in {"BUSY", "NO_ANSWER"}:
                if contact.attempts_count < max_attempts:
                    contact.status = "RETRY_SCHEDULED"
                    contact.next_attempt_at = now + timedelta(hours=retry_gap)
                else:
                    contact.status = "FAILED"
                    contact.next_attempt_at = None
            elif disposition == "DND":
                contact.status = "DND_EXCLUDED"
                contact.next_attempt_at = None
            else:
                contact.status = "COMPLETED"

            # Update campaign metrics from persisted contact outcomes
            if campaign:
                campaign.calls_dialed += 1
                s.flush()
                total_dialed = s.scalar(
                    select(func.sum(CampaignContactRow.attempts_count)).where(
                        CampaignContactRow.campaign_id == campaign.campaign_id
                    )
                ) or 0
                connected_count = s.scalar(
                    select(func.count(CampaignContactRow.contact_id)).where(
                        CampaignContactRow.campaign_id == campaign.campaign_id,
                        CampaignContactRow.last_disposition.in_(sorted(CONNECTED_OUTCOMES)),
                    )
                ) or 0
                campaign.answer_rate = round(connected_count / total_dialed, 2) if total_dialed else 0.0
                campaign.updated_at = now
                remaining = s.scalar(select(func.count(CampaignContactRow.contact_id)).where(
                    CampaignContactRow.campaign_id == campaign.campaign_id,
                    CampaignContactRow.status.in_(DIALABLE_STATUSES + ("DIALING",)),
                )) or 0
                if remaining == 0 and campaign.status == "ACTIVE":
                    campaign.status = "COMPLETED"

            s.commit()
            return self._serialize_contact(contact)

    @staticmethod
    def _serialize_campaign(row: CampaignRow, s=None) -> dict[str, Any]:
        stats: dict[str, int] = {}
        if s is not None:
            for status, count in s.execute(
                select(CampaignContactRow.status, func.count(CampaignContactRow.contact_id))
                .where(CampaignContactRow.campaign_id == row.campaign_id)
                .group_by(CampaignContactRow.status)
            ).all():
                stats[status] = count
        return {
            "category": row.category,
            "maxConcurrent": row.max_concurrent,
            "approvedBy": row.approved_by,
            "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
            "createdBy": row.created_by,
            "contactStats": stats,
            "id": row.campaign_id,
            "name": row.name,
            "objective": row.objective,
            "status": row.status,
            "scriptVersion": row.script_version,
            "segmentSize": row.segment_size,
            "maxAttempts": row.max_attempts,
            "retryGapHours": row.retry_gap_hours,
            "languages": row.languages_json,
            "region": row.region,
            "callsDialed": row.calls_dialed,
            "answerRate": row.answer_rate,
            "updatedAt": row.updated_at.isoformat(),
        }

    @staticmethod
    def _serialize_contact(row: CampaignContactRow) -> dict[str, Any]:
        return {
            "contact_id": row.contact_id,
            "campaign_id": row.campaign_id,
            "customer_ref": row.customer_ref,
            "phone": row.phone,
            "status": row.status,
            "attempts_count": row.attempts_count,
            "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "last_disposition": row.last_disposition,
            "last_session_id": row.last_session_id,
            "created_at": row.created_at.isoformat(),
        }
