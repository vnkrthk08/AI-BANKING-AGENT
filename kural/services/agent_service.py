"""Human agent roster: profiles, availability, skills, and workload metrics derived from real
case and callback records. No agents are created automatically — every roster entry is
registered by an authorised supervisor or operations manager.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from kural.persistence.database import Database
from kural.persistence.models import AgentRow, CallbackRow, CaseRow, UserRow
from kural.privacy.masking import mask_phone

AVAILABILITY_STATES = {"AVAILABLE", "BUSY", "ON_CALL", "BREAK", "OFFLINE"}
OPEN_CASE_STATUSES = ("NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER")
IST = ZoneInfo("Asia/Kolkata")


def _start_of_today_ist(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


class AgentService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_agents(self, availability: str | None = None, team: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as s:
            q = select(AgentRow)
            if availability:
                q = q.where(AgentRow.availability == availability)
            if team:
                q = q.where(AgentRow.team == team)
            rows = s.scalars(q.order_by(AgentRow.name)).all()
            metrics = self._metrics(s)
            return [self._serialize_agent(r, metrics.get(r.agent_id)) for r in rows]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            r = s.get(AgentRow, agent_id)
            return self._serialize_agent(r, self._metrics(s).get(agent_id)) if r else None

    def update_agent_availability(self, agent_id: str, availability: str) -> dict[str, Any]:
        availability = availability.upper()
        if availability not in AVAILABILITY_STATES:
            raise ValueError(f"Unknown availability {availability}")
        with self.database.session() as s:
            r = s.get(AgentRow, agent_id)
            if not r:
                raise KeyError(f"Agent not found: {agent_id}")
            r.availability = availability
            r.active_calls = 1 if availability == "ON_CALL" else 0
            r.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_agent(r, self._metrics(s).get(agent_id))

    def update_agent(self, agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.database.session() as s:
            r = s.get(AgentRow, agent_id)
            if not r:
                raise KeyError(f"Agent not found: {agent_id}")
            if "name" in patch and patch["name"]:
                r.name = str(patch["name"])[:128]
            if "team" in patch and patch["team"]:
                r.team = str(patch["team"])[:80]
            if "languages" in patch and isinstance(patch["languages"], list):
                r.languages_json = [str(x)[:20] for x in patch["languages"]]
            if "skills" in patch and isinstance(patch["skills"], list):
                r.skills_json = [str(x)[:40] for x in patch["skills"]]
            if "max_open_cases" in patch:
                r.max_open_cases = max(1, min(100, int(patch["max_open_cases"])))
            if "phone" in patch:
                r.phone = patch["phone"] or None
            if "email" in patch:
                r.email = patch["email"] or None
            r.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_agent(r, self._metrics(s).get(agent_id))

    def get_agent_workloads(self) -> list[dict[str, Any]]:
        with self.database.session() as s:
            metrics = self._metrics(s)
            agents = s.scalars(select(AgentRow)).all()
            return [{
                "agentId": a.agent_id,
                "assignedCases": metrics.get(a.agent_id, {}).get("open_cases", 0),
                "immediateCallbacks": metrics.get(a.agent_id, {}).get("due_callbacks", 0),
                "overdueCases": metrics.get(a.agent_id, {}).get("overdue_cases", 0),
                "capacity": a.max_open_cases,
                "utilizationPercent": round(100 * metrics.get(a.agent_id, {}).get("open_cases", 0) / max(a.max_open_cases, 1)),
            } for a in agents]

    def find_best_agent(self, preferred_language: str = "Hindi", issue_category: str = "APP_SUPPORT") -> dict[str, Any] | None:
        """Least-loaded AVAILABLE agent with the skill, preferring the customer's language."""
        with self.database.session() as s:
            counts = dict(s.execute(
                select(CaseRow.assigned_agent_id, func.count(CaseRow.case_id))
                .where(CaseRow.status.in_(OPEN_CASE_STATUSES), CaseRow.assigned_agent_id.is_not(None))
                .group_by(CaseRow.assigned_agent_id)
            ).all())
            best: tuple[tuple[int, int, str], AgentRow] | None = None
            for a in s.scalars(select(AgentRow).where(AgentRow.availability == "AVAILABLE")).all():
                skills = set(a.skills_json or [])
                if issue_category not in skills and "GENERAL_SUPPORT" not in skills and "APP_SUPPORT" not in skills:
                    continue
                load = counts.get(a.agent_id, 0)
                if load >= a.max_open_cases:
                    continue
                key = (0 if preferred_language in (a.languages_json or []) else 1, load, a.agent_id)
                if best is None or key < best[0]:
                    best = (key, a)
            return self._serialize_agent(best[1], None) if best else None

    def create_agent(
        self,
        name: str,
        team: str = "Digital support",
        languages: list[str] | None = None,
        skills: list[str] | None = None,
        availability: str = "OFFLINE",
        agent_id: str | None = None,
        user_id: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        max_open_cases: int = 12,
    ) -> dict[str, Any]:
        availability = availability.upper()
        if availability not in AVAILABILITY_STATES:
            raise ValueError(f"Unknown availability {availability}")
        with self.database.session() as s:
            now = datetime.now(timezone.utc)
            if user_id is not None:
                user = s.get(UserRow, user_id)
                if user is None:
                    raise ValueError("Linked user account does not exist")
                if s.scalar(select(AgentRow).where(AgentRow.user_id == user_id)) is not None:
                    raise ValueError("That user is already linked to an agent profile")
            if not agent_id:
                count = s.scalar(select(func.count(AgentRow.agent_id))) or 0
                agent_id = f"AG-{count + 1:03d}"
                while s.get(AgentRow, agent_id) is not None:
                    count += 1
                    agent_id = f"AG-{count + 1:03d}"
            elif s.get(AgentRow, agent_id) is not None:
                raise ValueError(f"Agent id {agent_id} already exists")
            row = AgentRow(
                agent_id=agent_id, name=name, team=team,
                languages_json=languages or ["English"], availability=availability,
                active_calls=0, handled_today=0, avg_resolution_min=0, sla_hit_percent=0,
                skills_json=skills or ["GENERAL_SUPPORT"], user_id=user_id, phone=phone, email=email,
                max_open_cases=max_open_cases, created_at=now, updated_at=now,
            )
            s.add(row)
            s.commit()
            return self._serialize_agent(row, None)

    def _metrics(self, s) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        today = _start_of_today_ist(now)
        window = now - timedelta(days=30)
        out: dict[str, dict[str, Any]] = {}
        for c in s.scalars(select(CaseRow).where(CaseRow.assigned_agent_id.is_not(None))).all():
            m = out.setdefault(c.assigned_agent_id, {"open_cases": 0, "overdue_cases": 0, "resolved_today": 0,
                                                     "res_minutes": [], "sla_met": 0, "sla_total": 0,
                                                     "due_callbacks": 0, "callbacks_done_today": 0})
            if c.status in OPEN_CASE_STATUSES:
                m["open_cases"] += 1
                if c.sla_due_at and c.sla_due_at < now:
                    m["overdue_cases"] += 1
            if c.resolved_at:
                if c.resolved_at >= today:
                    m["resolved_today"] += 1
                if c.resolved_at >= window:
                    start = c.assigned_at or c.created_at
                    m["res_minutes"].append((c.resolved_at - start).total_seconds() / 60)
                    m["sla_total"] += 1
                    if c.sla_due_at and c.resolved_at <= c.sla_due_at:
                        m["sla_met"] += 1
        for cb in s.scalars(select(CallbackRow).where(CallbackRow.assigned_agent_id.is_not(None))).all():
            m = out.setdefault(cb.assigned_agent_id, {"open_cases": 0, "overdue_cases": 0, "resolved_today": 0,
                                                      "res_minutes": [], "sla_met": 0, "sla_total": 0,
                                                      "due_callbacks": 0, "callbacks_done_today": 0})
            if cb.status == "DUE":
                m["due_callbacks"] += 1
            if cb.status == "COMPLETED" and cb.completed_at and cb.completed_at >= today:
                m["callbacks_done_today"] += 1
        return out

    @staticmethod
    def _serialize_agent(row: AgentRow, metrics: dict[str, Any] | None) -> dict[str, Any]:
        m = metrics or {}
        res = m.get("res_minutes") or []
        return {
            "id": row.agent_id,
            "name": row.name,
            "team": row.team,
            "languages": row.languages_json,
            "skills": row.skills_json,
            "availability": row.availability,
            "activeCalls": row.active_calls,
            "userId": row.user_id,
            "maskedPhone": mask_phone(row.phone) if row.phone else None,
            "transferCapable": bool(row.phone),
            "maxOpenCases": row.max_open_cases,
            "openCases": m.get("open_cases", 0),
            "overdueCases": m.get("overdue_cases", 0),
            "dueCallbacks": m.get("due_callbacks", 0),
            "handledToday": m.get("resolved_today", 0) + m.get("callbacks_done_today", 0),
            # Null when there is no resolved work to measure — never a placeholder value.
            "avgResolutionMin": round(sum(res) / len(res)) if res else None,
            "slaHitPercent": round(100 * m["sla_met"] / m["sla_total"]) if m.get("sla_total") else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        }
