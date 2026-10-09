"""Regression tests for Phase 3 Release Audit remediations.

Covers:
1. Bidirectional Alembic migration reproducibility (0001_initial <-> 0002_phase2_phase3_operations).
2. Pre-dispatch DND scrubbing in campaign worker queue.
3. Immediate active contact scrubbing when a customer toggles DND.
4. CSV formula injection sanitization in customer and call exports.
"""

import os
import tempfile
import uuid
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from kural.persistence.database import Database
from kural.persistence.models import Base, CampaignContactRow, CustomerRow
from kural.services.call_service import CallService
from kural.services.campaign_service import CampaignService
from kural.services.customer_service import CustomerService


def test_alembic_migration_bidirectional() -> None:
    """Verifies that alembic upgrade 0001_initial -> head and downgrade work reproducibly."""
    db_id = uuid.uuid4().hex[:8]
    db_path = os.path.join(tempfile.gettempdir(), f"kural_mig_test_{db_id}.db")

    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # Upgrade to 0001
        command.upgrade(cfg, "0001_initial")

        # Upgrade to head (0002)
        command.upgrade(cfg, "head")

        engine = create_engine(f"sqlite:///{db_path}")
        insp = inspect(engine)
        migrated_tables = set(insp.get_table_names()) - {"alembic_version"}
        model_tables = set(Base.metadata.tables.keys())

        assert migrated_tables == model_tables, f"Tables mismatch: {model_tables - migrated_tables}"

        for t in model_tables:
            cols = {c["name"] for c in insp.get_columns(t)}
            model_cols = {c.name for c in Base.metadata.tables[t].columns}
            assert cols == model_cols, f"Table {t} columns mismatch: {model_cols - cols}"

        # Downgrade back to 0001
        command.downgrade(cfg, "0001_initial")
        insp = inspect(engine)
        downgraded_tables = set(insp.get_table_names()) - {"alembic_version"}
        assert downgraded_tables == {"audit_events", "callbacks", "cases", "conversation_turns", "sessions"}

        # Re-upgrade to head
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        reup_tables = set(insp.get_table_names()) - {"alembic_version"}
        assert reup_tables == model_tables
    finally:
        engine.dispose()
        try:
            os.remove(db_path)
        except Exception:
            pass


def test_pre_dispatch_dnd_scrub(database: Database) -> None:
    """Verifies that a customer enrolled when non-DND is blocked at dispatch if marked DND later."""
    cust_svc = CustomerService(database)
    camp_svc = CampaignService(database)

    # 1. Create customer with DND=False
    cust = cust_svc.create_customer(
        full_name="Rajesh Kumar",
        phone="+919876543210",
        customer_ref="CUST-DND-TEST-01",
        dnd_status=False,
    )
    assert cust["dnd_status"] is False

    # 2. Create campaign & enroll contact
    camp = camp_svc.create_campaign(name="Adoption Sprint", status="ACTIVE")
    camp_id = camp["id"]
    contact = camp_svc.add_contact(camp_id, cust["customer_ref"], "+919876543210")
    assert contact["status"] == "PENDING"

    # 3. Customer toggles DND on
    cust_svc.create_customer(
        full_name="Rajesh Kumar",
        phone="+919876543210",
        customer_ref="CUST-DND-TEST-01",
        dnd_status=True,
    )

    # 4. Attempt to retrieve queued contacts for dispatch
    queued = camp_svc.get_queued_contacts(camp_id, batch_size=5)

    # Verify that contact was NOT queued for dialing and was scrubbed to DND_EXCLUDED
    assert len(queued) == 0

    with database.session() as s:
        db_contact = s.get(CampaignContactRow, contact["contact_id"])
        assert db_contact is not None
        assert db_contact.status == "DND_EXCLUDED"
        assert db_contact.next_attempt_at is None


def test_immediate_campaign_contact_scrub_on_dnd_toggle(database: Database) -> None:
    """Verifies that updating a customer to DND immediately scrubs pending campaign contacts."""
    cust_svc = CustomerService(database)
    camp_svc = CampaignService(database)

    # Create customer and campaign
    cust = cust_svc.create_customer(
        full_name="Pooja Sharma",
        phone="+919811122233",
        customer_ref="CUST-DND-TEST-02",
        dnd_status=False,
    )
    camp = camp_svc.create_campaign(name="Outbound KYC", status="ACTIVE")
    contact = camp_svc.add_contact(camp["id"], cust["customer_ref"], "+919811122233")
    assert contact["status"] == "PENDING"

    # Updating customer to DND
    cust_svc.create_customer(
        full_name="Pooja Sharma",
        phone="+919811122233",
        customer_ref="CUST-DND-TEST-02",
        dnd_status=True,
    )

    with database.session() as s:
        c = s.get(CampaignContactRow, contact["contact_id"])
        assert c.status == "DND_EXCLUDED"
        assert c.next_attempt_at is None


def test_csv_formula_injection_prevention(database: Database) -> None:
    """Verifies that formula injection triggers (=, +, -, @) are sanitized with leading single quote."""
    cust_svc = CustomerService(database)
    call_svc = CallService(database)

    # Inject customers with potential formula triggers
    cust_svc.create_customer(
        full_name="=cmd|'/C calc'!A0",
        phone="+919822233344",
        customer_ref="@CUST-FORMULA-1",
        account_type="+PREMIUM",
        branch="-MUMBAI",
    )

    csv_data = cust_svc.export_customers_csv()
    assert "'=cmd|'/C calc'!A0" in csv_data
    assert "'@CUST-FORMULA-1" in csv_data
    assert "'+PREMIUM" in csv_data
    assert "'-MUMBAI" in csv_data

    # Test call export formula sanitization
    call_svc.create_call_record(
        session_id="sess-formula-test",
        customer_ref="CUST-FORMULA-2",
        campaign_name="=HYPERLINK(\"http://malicious.com\")",
    )
    call_svc.update_call_by_session("sess-formula-test", {"disposition": "+CLOSED"})
    call_csv = call_svc.export_calls_csv()
    assert "'=HYPERLINK" in call_csv
    assert "'+CLOSED" in call_csv
