"""Tamper-evident audit ledger with cryptographic hash chaining and sequence verification."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import AuditLedgerRow, utcnow

logger = logging.getLogger("kural.audit.ledger")


class AuditLedgerService:
    """Manages immutable, append-only, cryptographically linked audit event ledgers."""

    GENESIS_HASH = "0" * 64

    def __init__(self, database: Database) -> None:
        self.db = database

    def record_entry(
        self,
        event_type: str,
        details: Dict[str, Any],
        actor_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> AuditLedgerRow:
        """Append an audit event cryptographically linked to the previous event hash."""
        with self.db.session() as s:
            # Query the latest sequence
            last_entry = s.scalars(
                select(AuditLedgerRow).order_by(AuditLedgerRow.sequence_number.desc()).limit(1)
            ).first()

            if last_entry is None:
                seq = 1
                prev_h = self.GENESIS_HASH
            else:
                seq = last_entry.sequence_number + 1
                prev_h = last_entry.event_hash

            details_serialized = json.dumps(details, sort_keys=True)
            hash_input = f"{prev_h}:{seq}:{event_type}:{actor_id or ''}:{role or ''}:{details_serialized}"
            event_h = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            row = AuditLedgerRow(
                sequence_number=seq,
                prev_hash=prev_h,
                event_hash=event_h,
                event_type=event_type,
                actor_id=actor_id,
                role=role,
                details_json=details,
                created_at=utcnow(),
            )
            s.add(row)
            s.commit()
            return row

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """Verify the cryptographic integrity of the entire audit hash chain.
        
        Returns (is_valid, corrupted_sequence_index).
        """
        with self.db.session() as s:
            entries = s.scalars(select(AuditLedgerRow).order_by(AuditLedgerRow.sequence_number.asc())).all()

            if not entries:
                return True, None

            expected_prev_hash = self.GENESIS_HASH
            expected_seq = 1

            for row in entries:
                # 1. Sequence continuity check (detects deletions)
                if row.sequence_number != expected_seq:
                    logger.critical("AUDIT_GAP_DETECTED: Sequence jumped from %d to %d", expected_seq - 1, row.sequence_number)
                    return False, expected_seq

                # 2. Previous hash link check
                if row.prev_hash != expected_prev_hash:
                    logger.critical("AUDIT_HASH_LINK_BROKEN at sequence %d", row.sequence_number)
                    return False, row.sequence_number

                # 3. Payload integrity check (detects in-place modification)
                details_serialized = json.dumps(row.details_json, sort_keys=True)
                hash_input = f"{row.prev_hash}:{row.sequence_number}:{row.event_type}:{row.actor_id or ''}:{row.role or ''}:{details_serialized}"
                recomputed_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

                if row.event_hash != recomputed_hash:
                    logger.critical("AUDIT_CONTENT_TAMPERED at sequence %d", row.sequence_number)
                    return False, row.sequence_number

                expected_prev_hash = row.event_hash
                expected_seq += 1

            return True, None

    def export_daily_seal(self) -> Dict[str, Any]:
        """Generate a tamper-evident daily seal summary for WORM / cloud immutable storage."""
        with self.db.session() as s:
            latest = s.scalars(select(AuditLedgerRow).order_by(AuditLedgerRow.sequence_number.desc()).limit(1)).first()
            if not latest:
                return {"status": "EMPTY", "last_sequence": 0, "head_hash": self.GENESIS_HASH}

            return {
                "status": "SEALED",
                "last_sequence": latest.sequence_number,
                "chain_head_hash": latest.event_hash,
                "sealed_at": utcnow().isoformat(),
            }
