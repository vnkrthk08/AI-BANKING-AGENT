"""Call domain service: call session tracking, dispositions, transcripts with PII masking, and recording audio binding."""

import csv
import io
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CallRecordRow, CampaignRow, ConversationTurnRow, CustomerRow, SessionRow
from kural.privacy.masking import mask_phone
from kural.services.recording_service import redact_pii


def sanitize_csv_value(val: Any) -> Any:
    """Escapes leading spreadsheet formula symbols to prevent CSV injection."""
    if isinstance(val, str) and val.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{val}"
    return val


class CallService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_call_record(
        self,
        session_id: str,
        customer_ref: str,
        campaign_id: str | None = None,
        campaign_name: str | None = None,
        channel: str = "BROWSER",
        call_id: str | None = None,
        provider_call_sid: str | None = None,
        status: str = "IN_PROGRESS",
    ) -> dict[str, Any]:
        call_id = call_id or f"CALL-{uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            customer = s.get(CustomerRow, customer_ref)
            if campaign_name is None and campaign_id:
                campaign = s.get(CampaignRow, campaign_id)
                campaign_name = campaign.name if campaign else None
            row = CallRecordRow(
                call_id=call_id,
                session_id=session_id,
                customer_ref=customer_ref,
                campaign_id=campaign_id,
                campaign_name=campaign_name or ("Voice Studio session" if channel == "BROWSER" else "Direct call"),
                masked_phone=mask_phone(customer.phone) if customer else "",
                language=customer.preferred_language if customer else "English",
                region=customer.region if customer else "",
                branch=customer.branch if customer else "",
                started_at=now,
                duration_sec=0,
                disposition=None,
                resolution_mode="AI",
                status=status,
                connected=channel == "BROWSER",
                consented=False,
                app_installed=bool(customer and customer.app_status in ("INSTALLED", "OUTDATED", "UPDATED")),
                app_updated=False,
                app_version=(customer.app_version if customer and customer.app_version else "—"),
                sentiment=0.0,
                issue_category=None,
                kural_state="READY",
                intent="UNKNOWN",
                policy_decision="ALLOWED",
                cost_inr=0.0,
                compliance_flags_json=[],
                feature_interest_json=[],
                summary="",
                recording_available=False,
                channel=channel,
                provider_call_sid=provider_call_sid,
                created_at=now,
            )
            existing = s.scalar(select(CallRecordRow).where(CallRecordRow.session_id == session_id))
            if existing is not None:
                return self._serialize_call(existing)

            sess = s.get(SessionRow, session_id)
            if sess is None:
                s.add(
                    SessionRow(
                        session_id=session_id,
                        customer_ref=customer_ref,
                        current_state="READY",
                        created_at=now,
                        updated_at=now,
                    )
                )
                s.flush()

            s.add(row)
            s.commit()
            return self._serialize_call(row)

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.get(CallRecordRow, call_id)
            return self._serialize_call(row) if row else None

    def get_call_by_session(self, session_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.scalar(select(CallRecordRow).where(CallRecordRow.session_id == session_id))
            return self._serialize_call(row) if row else None

    def update_call_by_session(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self.database.session() as s:
            row = s.scalar(select(CallRecordRow).where(CallRecordRow.session_id == session_id))
            if not row:
                return None
            for key, val in patch.items():
                if hasattr(row, key):
                    setattr(row, key, val)
            s.commit()
            return self._serialize_call(row)

    def list_calls(
        self,
        campaign_id: str | None = None,
        disposition: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.database.session() as s:
            q = select(CallRecordRow)
            if campaign_id:
                q = q.where(CallRecordRow.campaign_id == campaign_id)
            if disposition:
                q = q.where(CallRecordRow.disposition == disposition)
            if status:
                q = q.where(CallRecordRow.status == status)
            q = q.order_by(CallRecordRow.started_at.desc()).limit(limit).offset(offset)
            rows = s.scalars(q).all()
            return [self._serialize_call(r) for r in rows]

    def get_call_transcript(self, call_id: str) -> list[dict[str, Any]]:
        """Extracts turn-by-turn transcript for call with PII masking."""
        with self.database.session() as s:
            call = s.get(CallRecordRow, call_id)
            if not call:
                return []
            turns = s.scalars(
                select(ConversationTurnRow)
                .where(ConversationTurnRow.session_id == call.session_id)
                .order_by(ConversationTurnRow.turn_order)
            ).all()

            transcript: list[dict[str, Any]] = []
            for t in turns:
                # Customer utterance
                if t.sanitized_user_text:
                    cleaned_customer = redact_pii(t.sanitized_user_text)
                    transcript.append({
                        "id": f"t-{t.turn_id}-user",
                        "speaker": "CUSTOMER",
                        "text": cleaned_customer,
                        "time": t.timestamp.isoformat(),
                        "redacted": cleaned_customer != t.sanitized_user_text,
                    })
                # AVA response
                if t.response:
                    cleaned_ava = redact_pii(t.response)
                    transcript.append({
                        "id": f"t-{t.turn_id}-ava",
                        "speaker": "AVA",
                        "text": cleaned_ava,
                        "time": t.timestamp.isoformat(),
                        "redacted": False,
                    })
            return transcript

    def export_calls_csv(self) -> str:
        calls = self.list_calls(limit=10000)
        output = io.StringIO()
        fieldnames = [
            "id",
            "customerRef",
            "maskedPhone",
            "campaignName",
            "language",
            "region",
            "branch",
            "startedAt",
            "durationSec",
            "disposition",
            "resolutionMode",
            "status",
            "kuralState",
            "intent",
            "channel",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for c in calls:
            row = {k: sanitize_csv_value(c.get(k, "")) for k in fieldnames}
            writer.writerow(row)
        return output.getvalue()

    @staticmethod
    def _serialize_call(row: CallRecordRow) -> dict[str, Any]:
        return {
            "id": row.call_id,
            "sessionId": row.session_id,
            "customerRef": row.customer_ref,
            "maskedPhone": row.masked_phone,
            "campaignId": row.campaign_id or "",
            "campaignName": row.campaign_name,
            "language": row.language,
            "region": row.region,
            "branch": row.branch,
            "startedAt": row.started_at.isoformat(),
            "durationSec": row.duration_sec,
            "disposition": row.disposition,
            "resolutionMode": row.resolution_mode,
            "status": row.status,
            "connected": row.connected,
            "consented": row.consented,
            "appInstalled": row.app_installed,
            "appUpdated": row.app_updated,
            "appVersion": row.app_version,
            "sentiment": row.sentiment,
            "issueCategory": row.issue_category,
            "callbackId": row.callback_id,
            "escalationId": row.escalation_id,
            "kuralState": row.kural_state,
            "intent": row.intent,
            "policy": row.policy_decision,
            "costInr": row.cost_inr,
            "complianceFlags": row.compliance_flags_json,
            "featureInterest": row.feature_interest_json,
            "summary": row.summary,
            "recordingAvailable": row.recording_available,
            "channel": row.channel,
            "providerCallSid": row.provider_call_sid,
            "endedAt": row.ended_at.isoformat() if row.ended_at else None,
            "retentionUntil": None,
        }
