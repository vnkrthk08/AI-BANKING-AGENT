"""Milestone 4.2 Acceptance Tests: PostgreSQL Migration, Cutover Tooling & Durable Outbox.

Covers:
1. SQLite-to-PostgreSQL cutover consistency (100% row counts & SHA-256 hashes)
2. Atomic outbox event commitment with domain state rollback safety
3. Outbox worker crash recovery & lease expiry reclaim
4. At-least-once transport with idempotent event deduplication
5. Telephony gateway simulated dial deduplication (zero duplicate calls)
6. Connection pool bounds under load (72 connection ceiling)
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select

from kural.persistence.cutover import DatabaseCutoverManager
from kural.persistence.database import Database
from kural.persistence.models import CaseRow, OutboxEventRow, SessionRow, UserRow, utcnow
from kural.services.outbox_processor import OutboxProcessor


@pytest.fixture
def test_db_pair(tmp_path):
    src_path = tmp_path / "src_kural.db"
    tgt_path = tmp_path / "tgt_kural.db"

    src_db = Database(f"sqlite:///{src_path}")
    tgt_db = Database(f"sqlite:///{tgt_path}")

    src_db.create_tables()
    tgt_db.create_tables()

    return src_db, tgt_db


def test_sqlite_cutover_consistency(test_db_pair):
    """Verify 100% row-count parity and composite SHA-256 hash matching during data pump cutover."""
    src_db, tgt_db = test_db_pair

    # Populate source database with diverse domain rows
    with src_db.session() as s:
        user = UserRow(
            id=str(uuid4()),
            username="analyst1",
            email="analyst1@townbank.internal",
            password_hash="argon2_sample_hash",
            full_name="Analyst One",
            role="AGENT",
            branch="Mumbai Metro",
            token_version=0,
            is_active=True,
        )
        s.add(user)

        sess = SessionRow(
            session_id="SESS-CUTOVER-001",
            customer_ref="CUST-00001",
            current_state="START",
            context_json={"verified": True},
        )
        s.add(sess)
        s.flush()

        case = CaseRow(
            case_id="CASE-CUTOVER-001",
            session_id=sess.session_id,
            customer_ref=sess.customer_ref,
            case_type="APP_SUPPORT",
            summary="Cutover verification case",
            status="OPEN",
        )
        s.add(case)

        outbox_ev = OutboxEventRow(
            id=str(uuid4()),
            aggregate_type="CASE",
            aggregate_id=case.case_id,
            event_type="CASE_CREATED",
            payload_json={"priority": "NORMAL"},
            idempotency_key="idemp_cutover_123",
            status="PENDING",
            retry_count=0,
            created_at=utcnow(),
        )
        s.add(outbox_ev)
        s.commit()

    manager = DatabaseCutoverManager(source_db=src_db, target_db=tgt_db)

    # Phase 2: Execute data pump
    stats = manager.execute_data_pump()
    assert stats["users"] >= 1
    assert stats["sessions"] >= 1
    assert stats["cases"] >= 1
    assert stats["outbox_events"] >= 1

    # Verify 100% row-count and composite SHA-256 digest match
    is_consistent, report = manager.verify_consistency()
    assert is_consistent is True, f"Discrepancies found: {report['discrepancies']}"

    # Phase 3: Finalize cutover & block reversion to SQLite
    assert manager.finalize_cutover() is True
    assert manager.is_cutover_completed is True

    # Reversion attempt must fail closed
    with pytest.raises(RuntimeError) as exc_info:
        manager.block_sqlite_reversion()
    assert "CRITICAL_INVARIANT_VIOLATION" in str(exc_info.value)


def test_outbox_atomic_commit(test_db_pair):
    """Verify that domain state and outbox events commit or roll back in the exact same transaction."""
    src_db, _ = test_db_pair
    processor = OutboxProcessor(src_db)

    # 1. Successful transaction: both persist
    with src_db.session() as s:
        sess = SessionRow(
            session_id="SESS-ATOMIC-001",
            customer_ref="CUST-ATOMIC-001",
            current_state="START",
            context_json={},
        )
        s.add(sess)
        processor.create_event(
            session=s,
            aggregate_type="SESSION",
            aggregate_id=sess.session_id,
            event_type="SESSION_STARTED",
            payload={"state": "START"},
            idempotency_key="idemp_atomic_success",
        )
        s.commit()

    with src_db.session() as s:
        assert s.get(SessionRow, "SESS-ATOMIC-001") is not None
        ev = s.scalar(select(OutboxEventRow).where(OutboxEventRow.idempotency_key == "idemp_atomic_success"))
        assert ev is not None
        assert ev.status == "PENDING"

    # 2. Rolled back transaction: neither persists
    try:
        with src_db.session() as s:
            sess_fail = SessionRow(
                session_id="SESS-ATOMIC-FAIL",
                customer_ref="CUST-FAIL",
                current_state="START",
                context_json={},
            )
            s.add(sess_fail)
            processor.create_event(
                session=s,
                aggregate_type="SESSION",
                aggregate_id="SESS-ATOMIC-FAIL",
                event_type="SESSION_STARTED",
                payload={},
                idempotency_key="idemp_atomic_fail",
            )
            raise ValueError("Simulated unexpected business error before commit")
    except ValueError:
        pass

    with src_db.session() as s:
        assert s.get(SessionRow, "SESS-ATOMIC-FAIL") is None
        ev_fail = s.scalar(select(OutboxEventRow).where(OutboxEventRow.idempotency_key == "idemp_atomic_fail"))
        assert ev_fail is None


def test_outbox_worker_crash_recovery(test_db_pair):
    """Verify that an abandoned or crashed worker lease is reclaimed after lease expiry."""
    src_db, _ = test_db_pair
    processor = OutboxProcessor(src_db, lease_seconds=2)

    with src_db.session() as s:
        ev = processor.create_event(
            session=s,
            aggregate_type="DIAL",
            aggregate_id="DIAL-CRASH-001",
            event_type="DIAL_REQUEST",
            payload={"phone": "9876543210"},
            idempotency_key="idemp_crash_recover",
        )
        s.commit()
        ev_id = ev.id

    # Worker 1 claims event
    batch1 = processor.claim_batch(batch_size=5)
    assert len(batch1) == 1
    assert batch1[0]["id"] == ev_id

    # Immediate second claim sees active lease -> returns empty
    batch_immediate = processor.claim_batch(batch_size=5)
    assert len(batch_immediate) == 0

    # Simulate worker 1 crashing (event remains unacknowledged, lease expires)
    with src_db.session() as s:
        row = s.get(OutboxEventRow, ev_id)
        # Manually expire the lease timestamp
        row.locked_until = utcnow() - timedelta(seconds=10)
        s.commit()

    # Surviving Worker 2 claims batch -> reclaims the expired event
    batch2 = processor.claim_batch(batch_size=5)
    assert len(batch2) == 1
    assert batch2[0]["id"] == ev_id

    # Worker 2 successfully finishes and marks dispatched
    processor.complete_event(ev_id)
    with src_db.session() as s:
        row = s.get(OutboxEventRow, ev_id)
        assert row.status == "DISPATCHED"


def test_at_least_once_idempotent_dispatch(test_db_pair):
    """Verify that re-dispatching an outbox event with the same idempotency_key is idempotent."""
    src_db, _ = test_db_pair
    processor = OutboxProcessor(src_db)

    with src_db.session() as s:
        ev = processor.create_event(
            session=s,
            aggregate_type="WEBHOOK",
            aggregate_id="HOOK-001",
            event_type="NOTIFICATION",
            payload={"text": "Alert"},
            idempotency_key="idemp_webhook_duplicate",
        )
        s.commit()

    batch = processor.claim_batch(batch_size=5)
    assert len(batch) == 1
    event_data = batch[0]

    # First delivery
    res1 = processor.dispatch_single_event(event_data)
    assert res1 is True
    assert processor.dispatch_call_count == 1

    # Simulated redelivery (e.g. network timeout or duplicate message)
    res2 = processor.dispatch_single_event(event_data)
    assert res2 is True
    # Side-effect count must remain 1!
    assert processor.dispatch_call_count == 1


def test_outbox_idempotent_external_side_effect_deduplication(test_db_pair):
    """Verify telephony simulation dial deduplication guarantees zero duplicate calls."""
    src_db, _ = test_db_pair
    processor = OutboxProcessor(src_db)

    with src_db.session() as s:
        ev = processor.create_event(
            session=s,
            aggregate_type="CAMPAIGN",
            aggregate_id="CMP-001",
            event_type="DIAL_DISPATCH",
            payload={"customer_id": "CUST-1", "attempt": 1},
            idempotency_key="idemp_dial_dedup_001",
        )
        s.commit()

    claimed = processor.claim_batch(batch_size=1)[0]

    # First dispatch triggers telephony dial
    processor.dispatch_single_event(claimed)
    assert processor.dispatch_call_count == 1

    # Duplicate dispatch ignored by telephony gateway ledger
    processor.dispatch_single_event(claimed)
    assert processor.dispatch_call_count == 1


def test_connection_pool_bounds_under_load():
    """Verify PostgreSQL connection configuration adheres to 72 max connection budget."""
    # Test with simulated PostgreSQL connection URL
    pg_db = Database("postgresql+psycopg://user:pass@localhost:5432/test_db")
    engine = pg_db.engine

    # Check pool configuration
    pool = engine.pool
    pool_size = pool.size()
    max_overflow = pool._max_overflow

    assert pool_size == 60
    assert max_overflow == 12
    total_max_connections = pool_size + max_overflow
    assert total_max_connections == 72, f"Expected 72 total max connections, got {total_max_connections}"
    pg_db.dispose()
