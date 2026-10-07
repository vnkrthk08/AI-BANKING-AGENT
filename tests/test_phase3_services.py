"""Unit tests for Phase 3 operational domain services."""

import pytest
from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.services.agent_service import AgentService
from kural.services.call_service import CallService
from kural.services.campaign_service import CampaignService
from kural.services.customer_service import CustomerService, normalize_indian_phone
from kural.services.recording_service import create_synthetic_wav, redact_pii
from kural.services.report_service import ReportService


@pytest.fixture
def test_db():
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    return db


def test_phone_normalization_and_validation():
    assert normalize_indian_phone("9876543210") == "+919876543210"
    assert normalize_indian_phone("+91 98765-43210") == "+919876543210"
    assert normalize_indian_phone("09876543210") == "+919876543210"

    with pytest.raises(ValueError):
        normalize_indian_phone("1234567890")  # Invalid Indian mobile prefix

    with pytest.raises(ValueError):
        normalize_indian_phone("short")


def test_pii_redaction():
    text = "My phone is 9876543210 and card is 4111-2222-3333-4444. OTP is 123456. Aadhaar 1234-5678-9012."
    redacted = redact_pii(text)
    assert "+91 98XXX XX10" in redacted
    assert "XXXX-XXXX-XXXX-4444" in redacted
    assert "[REDACTED]" in redacted
    assert "XXXX-XXXX-9012" in redacted


def test_customer_service_import_export(test_db):
    svc = CustomerService(test_db)
    csv_data = """full_name,phone,language,app_status,dnd
Vikram Seth,9876543211,Hindi,INSTALLED,0
Sunita Rao,9876543212,Tamil,NOT_INSTALLED,1
Invalid User,1234,English,NOT_INSTALLED,0
"""
    result = svc.import_customers_csv(csv_data)
    assert result["imported"] == 2
    assert result["dnd_suppressed"] == 1
    assert result["skipped"] == 1

    cust = svc.get_customer_by_phone("9876543211")
    assert cust is not None
    assert cust["full_name"] == "Vikram Seth"

    exported = svc.export_customers_csv()
    assert "Vikram Seth" in exported


def test_campaign_service_lifecycle_and_retry(test_db):
    camp_svc = CampaignService(test_db)
    camp = camp_svc.create_campaign("Adoption Campaign", objective="App adoption", max_attempts=2, retry_gap_hours=24)
    cid = camp["id"]

    assert camp["status"] == "DRAFT"
    camp_svc.start_campaign(cid)
    assert camp_svc.get_campaign(cid)["status"] == "ACTIVE"

    # Add contact
    contact = camp_svc.add_contact(cid, "CUST-001", "9876543210")
    cnt_id = contact["contact_id"]

    # Queued check
    queued = camp_svc.get_queued_contacts(cid, batch_size=5)
    assert len(queued) == 1

    # First attempt: BUSY -> should retry
    camp_svc.record_attempt(cnt_id, "BUSY", "sess-test-1")
    updated = camp_svc.list_contacts(cid)[0]
    assert updated["status"] == "RETRY_SCHEDULED"
    assert updated["attempts_count"] == 1

    # Second attempt: BUSY -> attempts reaches max_attempts (2) -> FAILED
    camp_svc.record_attempt(cnt_id, "BUSY", "sess-test-2")
    final_contact = camp_svc.list_contacts(cid)[0]
    assert final_contact["status"] == "FAILED"


def test_agent_service_routing_and_workload(test_db):
    agent_svc = AgentService(test_db)
    agents = agent_svc.list_agents()
    assert len(agents) == 16  # 16 seeded agents

    # Test smart matching for Tamil speaker
    best = agent_svc.find_best_agent(preferred_language="Tamil", issue_category="APP_SUPPORT")
    assert best is not None
    assert "Tamil" in best["languages"]

    # Test workload summary
    workloads = agent_svc.get_agent_workloads()
    assert len(workloads) == 16


def test_call_and_report_service(test_db):
    call_svc = CallService(test_db)
    report_svc = ReportService(test_db)

    # Synthetic WAV creation
    wav_bytes = create_synthetic_wav(duration_sec=0.5)
    assert len(wav_bytes) > 44  # Valid WAV header + PCM samples

    # Create call
    call = call_svc.create_call_record("sess-report-01", "CUST-001", campaign_name="Adoption Q4")
    call_id = call["id"]

    # Update disposition to CLOSED
    call_svc.update_call_by_session("sess-report-01", {"disposition": "CLOSED", "duration_sec": 45, "status": "COMPLETED"})

    kpi = report_svc.get_kpi_summary()
    assert kpi["callsDialed"] == 1
    assert kpi["closed"] == 1
    assert kpi["averageDurationSec"] == 45.0

    # Schedule save
    saved = report_svc.save_schedule({"cadence": "DAILY", "time": "08:30", "recipient": "lead@bank.demo"})
    assert saved["recipient"] == "lead@bank.demo"

    # Audit logging
    audit = report_svc.record_audit("CAMPAIGN_UPDATE", "CAMPAIGN", "CMP-01", role="OPS_MANAGER")
    assert audit["action"] == "CAMPAIGN_UPDATE"
    assert len(report_svc.list_audits()) == 1
