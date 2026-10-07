"""Unit tests for Phase 3 database models and schema relationships."""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kural.persistence.models import (
    AgentRow,
    Base,
    CallRecordRow,
    CampaignContactRow,
    CampaignRow,
    CustomerRow,
    OperationsAuditEventRow,
    ReportScheduleRow,
    SessionRow,
)


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_customer_model_crud(memory_db: Session):
    customer = CustomerRow(
        customer_ref="CUST-00001",
        full_name="Rajesh Sharma",
        phone="+919876543210",
        email="rajesh@example.com",
        preferred_language="Hindi",
        app_status="INSTALLED",
        app_version="4.9.2",
        dnd_status=False,
        account_type="SAVINGS",
        branch="Delhi NCR",
        region="North",
    )
    memory_db.add(customer)
    memory_db.commit()

    retrieved = memory_db.get(CustomerRow, "CUST-00001")
    assert retrieved is not None
    assert retrieved.full_name == "Rajesh Sharma"
    assert retrieved.phone == "+919876543210"
    assert retrieved.dnd_status is False


def test_campaign_and_contact_relationship(memory_db: Session):
    campaign = CampaignRow(
        campaign_id="CMP-TEST-01",
        name="Test Q4 Campaign",
        objective="App adoption",
        status="ACTIVE",
        script_version="v2.0",
        segment_size=100,
        max_attempts=3,
        retry_gap_hours=24,
        languages_json=["Hindi", "English"],
        region="North",
    )
    memory_db.add(campaign)
    memory_db.flush()

    contact = CampaignContactRow(
        contact_id="CNT-TEST-01",
        campaign_id="CMP-TEST-01",
        customer_ref="CUST-00001",
        phone="+919876543210",
        status="PENDING",
    )
    memory_db.add(contact)
    memory_db.commit()

    retrieved_contact = memory_db.get(CampaignContactRow, "CNT-TEST-01")
    assert retrieved_contact is not None
    assert retrieved_contact.campaign_id == "CMP-TEST-01"
    assert retrieved_contact.status == "PENDING"


def test_call_record_and_session_binding(memory_db: Session):
    now = datetime.now(timezone.utc)
    sess = SessionRow(
        session_id="sess-phase3-01",
        customer_ref="CUST-00001",
        current_state="ENDED",
        context_json={},
        created_at=now,
        updated_at=now,
    )
    memory_db.add(sess)
    memory_db.flush()

    call = CallRecordRow(
        call_id="CALL-000001",
        session_id="sess-phase3-01",
        customer_ref="CUST-00001",
        campaign_name="Test Campaign",
        masked_phone="+91 98XXX XX210",
        language="Hindi",
        disposition="CLOSED",
        duration_sec=84,
        resolution_mode="AI",
        status="COMPLETED",
        sentiment=0.75,
    )
    memory_db.add(call)
    memory_db.commit()

    retrieved_call = memory_db.scalar(
        select(CallRecordRow).where(CallRecordRow.session_id == "sess-phase3-01")
    )
    assert retrieved_call is not None
    assert retrieved_call.disposition == "CLOSED"
    assert retrieved_call.duration_sec == 84


def test_agent_and_workload_models(memory_db: Session):
    agent = AgentRow(
        agent_id="AG-001",
        name="Aarav S.",
        team="Digital support · North",
        languages_json=["Hindi", "English"],
        availability="AVAILABLE",
        active_calls=0,
        handled_today=12,
        avg_resolution_min=8,
        sla_hit_percent=94,
    )
    memory_db.add(agent)
    memory_db.commit()

    retrieved_agent = memory_db.get(AgentRow, "AG-001")
    assert retrieved_agent is not None
    assert retrieved_agent.name == "Aarav S."
    assert "Hindi" in retrieved_agent.languages_json


def test_operations_audit_and_schedule_models(memory_db: Session):
    audit = OperationsAuditEventRow(
        event_id="AUD-000001",
        actor="OPS-001",
        actor_role="OPS_MANAGER",
        action="CAMPAIGN_LAUNCHED",
        resource_type="CAMPAIGN",
        resource_id="CMP-TEST-01",
        ip="192.0.2.1",
        detail="Campaign started successfully.",
    )
    schedule = ReportScheduleRow(
        schedule_id="SCH-000001",
        cadence="DAILY",
        time_of_day="09:00",
        formats_json=["PDF", "XLSX"],
        recipient="ops-team@townbank.demo",
    )
    memory_db.add(audit)
    memory_db.add(schedule)
    memory_db.commit()

    retrieved_audit = memory_db.get(OperationsAuditEventRow, "AUD-000001")
    assert retrieved_audit is not None
    assert retrieved_audit.action == "CAMPAIGN_LAUNCHED"

    retrieved_schedule = memory_db.get(ReportScheduleRow, "SCH-000001")
    assert retrieved_schedule is not None
    assert retrieved_schedule.recipient == "ops-team@townbank.demo"
