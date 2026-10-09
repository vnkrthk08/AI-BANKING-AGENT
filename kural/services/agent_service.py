"""Representative domain service: roster management, workload aggregation, and smart skill-based routing."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import AgentRow, CallbackRow, CaseRow


DEFAULT_AGENTS = [
    {"id": "AG-001", "name": "Aarav S.", "team": "Digital support · North", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-002", "name": "Aditi R.", "team": "Digital support · North", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "LOGIN_ISSUE"]},
    {"id": "AG-003", "name": "Ananya K.", "team": "Digital support · North", "languages": ["Tamil", "English"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-004", "name": "Arjun M.", "team": "Digital support · North", "languages": ["English", "Marathi"], "skills": ["APP_SUPPORT", "FEATURE_NOT_WORKING"]},
    {"id": "AG-005", "name": "Devika P.", "team": "Digital support · North", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "SECURITY_CONCERN"]},
    {"id": "AG-006", "name": "Ishaan D.", "team": "Digital support · North", "languages": ["Tamil", "English"], "skills": ["APP_SUPPORT", "COMPLAINT"]},
    {"id": "AG-007", "name": "Kabir N.", "team": "Digital support · North", "languages": ["English", "Marathi"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-008", "name": "Kavya T.", "team": "Digital support · North", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "APP_CRASH"]},
    {"id": "AG-009", "name": "Meera V.", "team": "Digital support · South", "languages": ["Tamil", "English", "Telugu"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-010", "name": "Neel G.", "team": "Digital support · South", "languages": ["English", "Kannada"], "skills": ["APP_SUPPORT", "LOGIN_ISSUE"]},
    {"id": "AG-011", "name": "Nisha B.", "team": "Digital support · South", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-012", "name": "Pranav C.", "team": "Digital support · South", "languages": ["Tamil", "English"], "skills": ["APP_SUPPORT", "SECURITY_CONCERN"]},
    {"id": "AG-013", "name": "Riya J.", "team": "Digital support · South", "languages": ["English", "Marathi"], "skills": ["APP_SUPPORT", "COMPLAINT"]},
    {"id": "AG-014", "name": "Sana F.", "team": "Digital support · South", "languages": ["Hindi", "English"], "skills": ["APP_SUPPORT", "FEATURE_NOT_WORKING"]},
    {"id": "AG-015", "name": "Vihaan L.", "team": "Digital support · South", "languages": ["Tamil", "English"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
    {"id": "AG-016", "name": "Zoya H.", "team": "Digital support · South", "languages": ["Hindi", "English", "Urdu"], "skills": ["APP_SUPPORT", "GENERAL_SUPPORT"]},
]


class AgentService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        with self.database.session() as s:
            count = s.scalar(select(AgentRow).limit(1))
            if count is None:
                now = datetime.now(timezone.utc)
                for index, a in enumerate(DEFAULT_AGENTS):
                    avail = "AVAILABLE" if index < 8 else ("ON_CALL" if index < 12 else "BREAK")
                    row = AgentRow(
                        agent_id=a["id"],
                        name=a["name"],
                        team=a["team"],
                        languages_json=a["languages"],
                        availability=avail,
                        active_calls=1 if avail == "ON_CALL" else 0,
                        handled_today=10 + (index * 2),
                        avg_resolution_min=8 + (index % 5),
                        sla_hit_percent=92 + (index % 7),
                        skills_json=a["skills"],
                        created_at=now,
                        updated_at=now,
                    )
                    s.add(row)
                s.commit()

    def list_agents(self, availability: str | None = None, team: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as s:
            q = select(AgentRow)
            if availability:
                q = q.where(AgentRow.availability == availability)
            if team:
                q = q.where(AgentRow.team == team)
            q = q.order_by(AgentRow.agent_id)
            rows = s.scalars(q).all()
            return [self._serialize_agent(r) for r in rows]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self.database.session() as s:
            r = s.get(AgentRow, agent_id)
            return self._serialize_agent(r) if r else None

    def update_agent_availability(self, agent_id: str, availability: str) -> dict[str, Any]:
        with self.database.session() as s:
            r = s.get(AgentRow, agent_id)
            if not r:
                raise KeyError(f"Agent not found: {agent_id}")
            r.availability = availability
            r.active_calls = 1 if availability == "ON_CALL" else 0
            r.updated_at = datetime.now(timezone.utc)
            s.commit()
            return self._serialize_agent(r)

    def get_agent_workloads(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self.database.session() as s:
            agents = s.scalars(select(AgentRow)).all()
            cases = s.scalars(select(CaseRow)).all()
            callbacks = s.scalars(select(CallbackRow)).all()

            workloads = []
            for a in agents:
                assigned_cases = [c for c in cases if c.status != "RESOLVED" and getattr(c, "assigned_agent_id", None) == a.agent_id]
                immediate_cbs = [cb for cb in callbacks if cb.assigned_agent_id == a.agent_id and cb.status == "IMMEDIATE"]
                overdue = [c for c in assigned_cases if c.sla_due_at and c.sla_due_at < now]
                utilization = 85 if a.availability == "ON_CALL" else (40 if a.availability == "AVAILABLE" else 0)

                workloads.append({
                    "agentId": a.agent_id,
                    "assignedCases": len(assigned_cases),
                    "immediateCallbacks": len(immediate_cbs),
                    "overdueCases": len(overdue),
                    "utilizationPercent": utilization,
                })
            return workloads

    def find_best_agent(self, preferred_language: str = "Hindi", issue_category: str = "APP_SUPPORT") -> dict[str, Any] | None:
        """Scores candidate agents based on language match, skill match, availability, and active load."""
        with self.database.session() as s:
            agents = s.scalars(select(AgentRow)).all()
            cases = s.scalars(select(CaseRow).where(CaseRow.status.in_(["NEW", "ASSIGNED", "IN_PROGRESS"]))).all()

            scored: list[tuple[int, AgentRow]] = []
            for a in agents:
                score = 0
                # 1. Language match (+40)
                if preferred_language in a.languages_json:
                    score += 40
                elif "English" in a.languages_json:
                    score += 15

                # 2. Skill match (+30)
                if issue_category in a.skills_json:
                    score += 30
                elif "APP_SUPPORT" in a.skills_json:
                    score += 15

                # 3. Availability (+20 for AVAILABLE, +5 for ON_CALL)
                if a.availability == "AVAILABLE":
                    score += 20
                elif a.availability == "ON_CALL":
                    score += 5
                else:
                    score -= 50  # Strongly penalize BREAK or OFFLINE

                # 4. Workload balancing (-2 per currently active assigned case)
                active_count = sum(1 for c in cases if getattr(c, "assigned_agent_id", None) == a.agent_id)
                score -= (active_count * 2)

                scored.append((score, a))

            if not scored:
                return None
            scored.sort(key=lambda x: x[0], reverse=True)
            best_agent = scored[0][1]
            return self._serialize_agent(best_agent)

    def create_agent(
        self,
        name: str,
        team: str = "Digital support · Tier 1",
        languages: list[str] | None = None,
        skills: list[str] | None = None,
        availability: str = "AVAILABLE",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from sqlalchemy import func
        with self.database.session() as s:
            now = datetime.now(timezone.utc)
            if not agent_id:
                count = s.scalar(select(func.count(AgentRow.agent_id))) or 0
                agent_id = f"AG-{count + 1:03d}"
            row = AgentRow(
                agent_id=agent_id,
                name=name,
                team=team,
                languages_json=languages or ["Hindi", "English"],
                availability=availability,
                active_calls=0,
                handled_today=0,
                avg_resolution_min=0,
                sla_hit_percent=100.0,
                skills_json=skills or ["APP_SUPPORT", "GENERAL_SUPPORT"],
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            s.commit()
            return self._serialize_agent(row)

    @staticmethod
    def _serialize_agent(row: AgentRow) -> dict[str, Any]:
        return {
            "id": row.agent_id,
            "name": row.name,
            "team": row.team,
            "languages": row.languages_json,
            "availability": row.availability,
            "activeCalls": row.active_calls,
            "handledToday": row.handled_today,
            "avgResolutionMin": row.avg_resolution_min,
            "slaHitPercent": row.sla_hit_percent,
        }

