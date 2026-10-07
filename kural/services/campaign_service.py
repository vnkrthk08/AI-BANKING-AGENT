"""Campaign domain service: campaign lifecycle, contact queue management, retry scheduling, and pacing stats."""

import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CampaignContactRow, CampaignRow, CustomerRow
from kural.services.customer_service import normalize_indian_phone


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
            created_at=now,
            updated_at=now,
        )
        with self.database.session() as s:
            s.add(row)
            s.commit()
            return self._serialize_campaign(row)

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.get(CampaignRow, campaign_id)
            return self._serialize_campaign(row) if row else None

    def list_campaigns(self, status: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as s:
            query = select(CampaignRow)
            if status:
                query = query.where(CampaignRow.status == status)
            if region:
                query = query.where(CampaignRow.region == region)
            query = query.order_by(CampaignRow.created_at.desc())
            rows = s.scalars(query).all()
            return [self._serialize_campaign(r) for r in rows]

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
            row.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_campaign(row)

    def start_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self.update_campaign(campaign_id, {"status": "ACTIVE"})

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
        """Retrieves dialable contacts: PENDING, QUEUED, or RETRY_SCHEDULED where retry time has elapsed."""
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
                .limit(batch_size)
            )
            rows = s.scalars(q).all()
            for r in rows:
                r.status = "QUEUED"
            s.commit()
            return [self._serialize_contact(r) for r in rows]

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

            campaign = s.get(CampaignRow, contact.campaign_id)
            max_attempts = campaign.max_attempts if campaign else 3
            retry_gap = campaign.retry_gap_hours if campaign else 24

            contact.attempts_count += 1
            contact.last_attempt_at = now
            contact.last_disposition = disposition
            contact.last_session_id = session_id

            if disposition in {"CLOSED", "CALLBACK_SCHEDULED", "ESCALATED", "NOT_INTERESTED"}:
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

            # Update campaign metrics
            if campaign:
                campaign.calls_dialed += 1
                # Calculate answer rate: contacts with connected/completed disposition
                total_dialed = s.scalar(
                    select(func.sum(CampaignContactRow.attempts_count)).where(
                        CampaignContactRow.campaign_id == campaign.campaign_id
                    )
                ) or 1
                connected_count = s.scalar(
                    select(func.count(CampaignContactRow.contact_id)).where(
                        CampaignContactRow.campaign_id == campaign.campaign_id,
                        CampaignContactRow.last_disposition.in_(
                            ["CLOSED", "CALLBACK_SCHEDULED", "ESCALATED", "NOT_INTERESTED"]
                        ),
                    )
                ) or 0
                campaign.answer_rate = round(connected_count / max(total_dialed, 1), 2)
                campaign.updated_at = now

            s.commit()
            return self._serialize_contact(contact)

    @staticmethod
    def _serialize_campaign(row: CampaignRow) -> dict[str, Any]:
        return {
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
