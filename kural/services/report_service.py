"""Reporting and audit domain service: KPI computation, report schedule persistence, and operations audit log."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CallRecordRow, OperationsAuditEventRow, ReportScheduleRow


# Earlier builds stored the final NLU intent of text sessions as the disposition.
LEGACY_DISPOSITIONS = {
    "WANTS_HUMAN": "ESCALATED", "FRAUD_REPORT": "ESCALATED", "UPDATE_FAILURE": "ESCALATED", "APP_UPDATE_ISSUE": "ESCALATED",
    "CALLBACK": "CALLBACK_SCHEDULED", "BUSY": "CALLBACK_SCHEDULED", "OPT_OUT": "OPTED_OUT",
    "UPDATE_SUCCESS": "CLOSED", "AFFIRM": "CLOSED", "NEGATE": "CLOSED", "APP_NOT_INSTALLED": "CLOSED",
    "OUT_OF_SCOPE": "CLOSED", "ABUSE": "CLOSED", "LOW_CONFIDENCE": "CLOSED", "OTHER": "CLOSED",
}


class ReportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_kpi_summary(self, campaign_id: str | None = None) -> dict[str, Any]:
        """Call KPIs computed only from persisted call records (no placeholder values)."""
        with self.database.session() as s:
            q = select(CallRecordRow)
            if campaign_id:
                q = q.where(CallRecordRow.campaign_id == campaign_id)
            calls = s.scalars(q).all()

            total = len(calls)
            connected = [c for c in calls if c.connected]
            by_disposition: dict[str, int] = {}
            for c in calls:
                key = c.disposition or ("IN_PROGRESS" if c.status == "IN_PROGRESS" else "UNKNOWN")
                by_disposition[key] = by_disposition.get(key, 0) + 1
            completed = [c for c in calls if c.status != "IN_PROGRESS"]
            return {
                "callsDialed": total,
                "connected": len(connected),
                "answerRate": round(len(connected) / total, 2) if total else None,
                "closed": by_disposition.get("CLOSED", 0),
                "callbacks": by_disposition.get("CALLBACK_SCHEDULED", 0),
                "escalated": by_disposition.get("ESCALATED", 0),
                "noResponse": by_disposition.get("NO_RESPONSE", 0),
                "refusedDnd": by_disposition.get("DND", 0),
                "averageDurationSec": round(sum(c.duration_sec for c in completed) / len(completed), 1) if completed else None,
                "byDisposition": by_disposition,
            }

    def get_overview(self) -> dict[str, Any]:
        """Operational overview for the Overview hub, derived from persisted records only."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from kural.persistence.models import AgentRow, CallbackRow, CampaignRow, CaseRow, NotificationDeliveryRow

        ist = ZoneInfo("Asia/Kolkata")
        now = datetime.now(timezone.utc)
        today_start = now.astimezone(ist).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        window_start = today_start - timedelta(days=13)
        open_case_statuses = ("NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER")
        with self.database.session() as s:
            calls = s.scalars(select(CallRecordRow).where(CallRecordRow.started_at >= window_start)).all()
            daily: dict[str, dict[str, int]] = {}
            for i in range(14):
                d = (window_start + timedelta(days=i)).astimezone(ist).date().isoformat()
                daily[d] = {"calls": 0, "connected": 0, "resolved": 0}
            for c in calls:
                d = c.started_at.astimezone(ist).date().isoformat()
                if d in daily:
                    daily[d]["calls"] += 1
                    daily[d]["connected"] += int(c.connected)
                    daily[d]["resolved"] += int(c.disposition == "CLOSED")
            today_calls = [c for c in calls if c.started_at >= today_start]
            outcomes: dict[str, int] = {}
            for c in calls:
                if c.disposition:
                    key = LEGACY_DISPOSITIONS.get(c.disposition, c.disposition)
                    outcomes[key] = outcomes.get(key, 0) + 1
            stale_cutoff = now - timedelta(hours=2)
            live_calls = s.scalar(select(func.count(CallRecordRow.call_id)).where(
                CallRecordRow.status == "IN_PROGRESS", CallRecordRow.started_at >= stale_cutoff)) or 0

            open_cases = s.scalars(select(CaseRow).where(CaseRow.status.in_(open_case_statuses))).all()
            callbacks = s.scalars(select(CallbackRow).where(CallbackRow.status.in_(("SCHEDULED", "DUE", "DIALING", "REQUESTED")))).all()
            agents = s.scalars(select(AgentRow)).all()
            failed_deliveries = s.scalar(select(func.count(NotificationDeliveryRow.id)).where(
                NotificationDeliveryRow.status == "FAILED")) or 0
            active_campaigns = s.scalar(select(func.count(CampaignRow.campaign_id)).where(CampaignRow.status == "ACTIVE")) or 0

            return {
                "generatedAt": now.isoformat(),
                "today": {
                    "calls": len(today_calls),
                    "connected": sum(1 for c in today_calls if c.connected),
                    "resolvedByAi": sum(1 for c in today_calls if c.disposition == "CLOSED"),
                    "escalated": sum(1 for c in today_calls if c.disposition == "ESCALATED"),
                    "callbacksBooked": sum(1 for c in today_calls if c.disposition == "CALLBACK_SCHEDULED"),
                    "noResponse": sum(1 for c in today_calls if c.disposition == "NO_RESPONSE"),
                },
                "liveCalls": live_calls,
                "queues": {
                    "openCases": len(open_cases),
                    "unassignedCases": sum(1 for c in open_cases if not c.assigned_agent_id),
                    "slaBreached": sum(1 for c in open_cases if c.sla_due_at and c.sla_due_at < now),
                    "urgentCases": sum(1 for c in open_cases if c.priority == "Urgent"),
                    "scheduledCallbacks": sum(1 for c in callbacks if c.status == "SCHEDULED"),
                    "dueCallbacks": sum(1 for c in callbacks if c.status == "DUE"
                                        or (c.status == "SCHEDULED" and c.scheduled_at_utc and c.scheduled_at_utc < now)),
                    "callbacksNeedingTime": sum(1 for c in callbacks if c.status == "REQUESTED"),
                },
                "team": {
                    "total": len(agents),
                    "available": sum(1 for a in agents if a.availability == "AVAILABLE"),
                    "onCall": sum(1 for a in agents if a.availability == "ON_CALL"),
                },
                "campaigns": {"active": active_campaigns},
                "notifications": {"failedDeliveries": failed_deliveries},
                "dailyVolume": [{"date": d, **v} for d, v in daily.items()],
                "outcomes14d": outcomes,
            }

    def list_schedules(self) -> list[dict[str, Any]]:
        with self.database.session() as s:
            rows = s.scalars(select(ReportScheduleRow).order_by(ReportScheduleRow.created_at.desc())).all()
            return [
                {
                    "id": r.schedule_id,
                    "cadence": r.cadence,
                    "time": r.time_of_day,
                    "formats": r.formats_json,
                    "recipient": r.recipient,
                    "enabled": r.enabled,
                    "demoOnly": r.demo_only,
                    "createdAt": r.created_at.isoformat(),
                }
                for r in rows
            ]

    def save_schedule(self, data: dict[str, Any]) -> dict[str, Any]:
        sid = data.get("id") or f"SCH-{uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        row = ReportScheduleRow(
            schedule_id=sid,
            cadence=data.get("cadence", "DAILY"),
            time_of_day=data.get("time", "08:00"),
            formats_json=data.get("formats", ["PDF", "XLSX"]),
            recipient=data.get("recipient") or "",
            enabled=data.get("enabled", True),
            demo_only=data.get("demoOnly", True),
            created_at=now,
        )
        with self.database.session() as s:
            s.add(row)
            s.commit()
            return {
                "id": row.schedule_id,
                "cadence": row.cadence,
                "time": row.time_of_day,
                "formats": row.formats_json,
                "recipient": row.recipient,
                "enabled": row.enabled,
                "demoOnly": row.demo_only,
                "createdAt": row.created_at.isoformat(),
            }

    def record_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        role: str = "OPS_MANAGER",
        actor: str = "OPS-001",
        detail: str = "",
        ip: str = "127.0.0.1",
    ) -> dict[str, Any]:
        aid = f"AUD-{uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        row = OperationsAuditEventRow(
            event_id=aid,
            actor=actor,
            actor_role=role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            detail=detail or "Operations audit event logged under banking controls",
            timestamp=now,
        )
        with self.database.session() as s:
            s.add(row)
            s.commit()
            return self._serialize_audit(row)

    def list_audits(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as s:
            rows = s.scalars(
                select(OperationsAuditEventRow).order_by(OperationsAuditEventRow.timestamp.desc()).limit(limit)
            ).all()
            return [self._serialize_audit(r) for r in rows]

    @staticmethod
    def _serialize_audit(row: OperationsAuditEventRow) -> dict[str, Any]:
        return {
            "id": row.event_id,
            "actor": row.actor,
            "actorRole": row.actor_role,
            "action": row.action,
            "resourceType": row.resource_type,
            "resourceId": row.resource_id,
            "timestamp": row.timestamp.isoformat(),
            "ip": row.ip,
            "detail": row.detail,
        }
