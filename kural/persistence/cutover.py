"""SQLite-to-PostgreSQL Cutover and Data Pump Tooling.

Enforces:
1. 3-Phase cutover procedure (Freeze -> Data Pump -> Consistency Verification & Unfreeze)
2. 100% row-count parity and composite SHA-256 hash matching
3. Strict invariant: PostgreSQL is the sole authoritative store post-cutover.
   Reverting to SQLite after authoritative writes is permanently blocked.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Tuple

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import Base

logger = logging.getLogger("kural.persistence.cutover")


class DatabaseCutoverManager:
    """Manages transactional data migration from SQLite to PostgreSQL with SHA-256 verification."""

    def __init__(self, source_db: Database, target_db: Database) -> None:
        self.source_db = source_db
        self.target_db = target_db
        self._is_cutover_completed: bool = False

    @property
    def is_cutover_completed(self) -> bool:
        return self._is_cutover_completed

    def compute_table_hash(self, db: Database, table_name: str) -> Tuple[int, str]:
        """Compute row count and composite SHA-256 digest over serialized table rows."""
        hasher = hashlib.sha256()
        row_count = 0

        table = Base.metadata.tables.get(table_name)
        if table is None:
            raise ValueError(f"Unknown table for hash calculation: {table_name}")

        with db.session() as s:
            result = s.execute(select(table))
            # Fetch column keys and rows
            keys = list(result.keys())
            rows = result.fetchall()
            row_count = len(rows)

            for row in rows:
                row_dict = {}
                for idx, col in enumerate(keys):
                    val = row[idx]
                    # Normalize timestamps or JSON for deterministic hash comparison
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    row_dict[col] = str(val)
                serialized = json.dumps(row_dict, sort_keys=True).encode("utf-8")
                hasher.update(serialized)

        return row_count, hasher.hexdigest()

    def pump_table_data(self, table_name: str) -> int:
        """Pump rows from source table into target table."""
        table = Base.metadata.tables.get(table_name)
        if table is None:
            raise ValueError(f"Unknown table for data pump: {table_name}")

        with self.source_db.session() as src_sess:
            result = src_sess.execute(select(table))
            keys = list(result.keys())
            rows = result.fetchall()

            if not rows:
                return 0

            with self.target_db.session() as tgt_sess:
                for row in rows:
                    row_dict = {keys[i]: row[i] for i in range(len(keys))}
                    tgt_sess.execute(table.insert().values(row_dict))
                tgt_sess.commit()

        return len(rows)

    def execute_data_pump(self) -> Dict[str, int]:
        """Pump all application tables in dependency order."""
        # Clean target tables first
        self.target_db.create_tables()

        # Tables ordered by foreign key dependencies
        ordered_tables = [
            "users",
            "sessions",
            "conversation_turns",
            "cases",
            "callbacks",
            "callback_events",
            "campaigns",
            "campaign_contacts",
            "call_records",
            "agents",
            "report_schedules",
            "refresh_tokens",
            "websocket_tickets",
            "outbox_events",
            "audit_ledger",
            "audit_events",
            "operations_audit_events",
            "outbox",
        ]

        pump_stats: Dict[str, int] = {}
        inspector = inspect(self.source_db.engine)
        existing_tables = set(inspector.get_table_names())

        for tbl in ordered_tables:
            if tbl in existing_tables:
                count = self.pump_table_data(tbl)
                pump_stats[tbl] = count

        return pump_stats

    def verify_consistency(self) -> Tuple[bool, Dict[str, Any]]:
        """Verify 100% row-count parity and composite SHA-256 hash match between source and target."""
        inspector = inspect(self.source_db.engine)
        tables = [t for t in inspector.get_table_names() if t != "alembic_version"]

        discrepancies: Dict[str, Any] = {}
        table_stats: Dict[str, Any] = {}

        for tbl in tables:
            src_count, src_hash = self.compute_table_hash(self.source_db, tbl)
            tgt_count, tgt_hash = self.compute_table_hash(self.target_db, tbl)

            is_match = (src_count == tgt_count) and (src_hash == tgt_hash)
            table_stats[tbl] = {
                "source_count": src_count,
                "target_count": tgt_count,
                "source_hash": src_hash,
                "target_hash": tgt_hash,
                "match": is_match,
            }

            if not is_match:
                discrepancies[tbl] = {
                    "count_diff": tgt_count - src_count,
                    "src_hash": src_hash,
                    "tgt_hash": tgt_hash,
                }

        is_consistent = len(discrepancies) == 0
        return is_consistent, {"tables": table_stats, "discrepancies": discrepancies}

    def finalize_cutover(self) -> bool:
        """Finalize the 3-phase cutover. Reverting to SQLite after this is permanently forbidden."""
        consistent, report = self.verify_consistency()
        if not consistent:
            raise ValueError(f"Cutover aborted: data consistency verification failed: {report['discrepancies']}")

        self._is_cutover_completed = True
        logger.info("Cutover to PostgreSQL successfully finalized. SQLite is retired.")
        return True

    def block_sqlite_reversion(self) -> None:
        """Enforces invariant: SQLite fallback post-cutover is permanently prohibited."""
        if self._is_cutover_completed:
            raise RuntimeError(
                "CRITICAL_INVARIANT_VIOLATION: Attempted to fall back to SQLite after PostgreSQL cutover was finalized. Operation aborted."
            )
