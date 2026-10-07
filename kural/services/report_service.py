"""Reporting and audit domain service: KPI computation, report schedule persistence, and operations audit log."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import CallRecordRow, OperationsAuditEventRow, ReportScheduleRow


class ReportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_kpi_summary(self, campaign_id: str | None = None) -> dict[str, Any]:
        with self.database.session() as s:
            q = select(CallRecordRow)
            if campaign_id:
                q = q.where(CallRecordRow.campaign_id == campaign_id)
            calls = s.scalars(q).all()

            total_dialed = len(calls)
            if total_dialed == 0:
                return {
                    "callsDialed": 0,
                    "connected": 0,
                    "answerRate": 0.0,
                    "closed": 0,
                    "callbacks": 0,
                    "escalated": 0,
                    "refusedDnd": 0,
                    "averageDurationSec": 0,
                    "averageSentiment": 0.0,
                    "costPerCallInr": 0.50,
                    "costPerResolvedInr": 1.20,
                }

            connected = [c for c in calls if c.connected]
            closed = [c for c in calls if c.disposition == "CLOSED"]
            callbacks = [c for c in calls if c.disposition == "CALLBACK_SCHEDULED"]
            escalated = [c for c in calls if c.disposition == "ESCALATED"]
            dnd = [c for c in calls if c.disposition == "DND"]

            avg_dur = sum(c.duration_sec for c in calls) / total_dialed
            avg_sent = sum(c.sentiment for c in calls) / total_dialed
            tot_cost = sum(c.cost_inr for c in calls)

            return {
                "callsDialed": total_dialed,
                "connected": len(connected),
                "answerRate": round(len(connected) / total_dialed, 2),
                "closed": len(closed),
                "callbacks": len(callbacks),
                "escalated": len(escalated),
                "refusedDnd": len(dnd),
                "averageDurationSec": round(avg_dur, 1),
                "averageSentiment": round(avg_sent, 2),
                "costPerCallInr": round(tot_cost / total_dialed, 2),
                "costPerResolvedInr": round(tot_cost / max(len(closed), 1), 2),
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
            recipient=data.get("recipient", "ops@townbank.demo"),
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
