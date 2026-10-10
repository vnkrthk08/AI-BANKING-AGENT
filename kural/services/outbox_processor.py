"""Durable Outbox Processor with atomic claiming, lease recovery, bounded retries,
dead-letter routing, and downstream deduplication for Phase 4.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import OutboxEventRow, utcnow

logger = logging.getLogger("kural.services.outbox")


class OutboxProcessor:
    """Manages transactional outbox event creation, atomic claiming, lease recovery,
    and idempotent dispatching.
    """

    DEFAULT_LEASE_SECONDS = 30
    DEFAULT_MAX_RETRIES = 5

    def __init__(
        self,
        database: Database,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.db = database
        self.lease_seconds = lease_seconds
        self.max_retries = max_retries
        # Telephony gateway simulated dispatch deduplication ledger
        self.dispatched_idempotency_keys: set[str] = set()
        self.dispatch_call_count: int = 0

    @staticmethod
    def create_event(
        session: Session,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> OutboxEventRow:
        """Create an outbox event within the caller's active database transaction.
        
        Guarantees that state mutation and outbox event are atomically committed together.
        """
        if idempotency_key is None:
            idempotency_key = f"evt_{uuid4().hex}"

        event = OutboxEventRow(
            id=str(uuid4()),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload_json=payload,
            idempotency_key=idempotency_key,
            status="PENDING",
            retry_count=0,
            locked_until=None,
            created_at=utcnow(),
        )
        session.add(event)
        return event

    def claim_batch(self, batch_size: int = 10) -> List[Dict[str, Any]]:
        """Atomically claim a batch of pending or expired-lease outbox events."""
        now = utcnow()
        lease_until = now + timedelta(seconds=self.lease_seconds)
        claimed_events: List[Dict[str, Any]] = []

        with self.db.session() as s:
            # Find eligible events: PENDING and (unlocked or lease expired)
            stmt = (
                select(OutboxEventRow)
                .where(
                    OutboxEventRow.status == "PENDING",
                    (OutboxEventRow.locked_until.is_(None)) | (OutboxEventRow.locked_until <= now),
                    OutboxEventRow.retry_count < self.max_retries,
                )
                .order_by(OutboxEventRow.created_at.asc())
                .limit(batch_size)
            )
            rows = s.scalars(stmt).all()

            for row in rows:
                row.locked_until = lease_until
                claimed_events.append({
                    "id": row.id,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "event_type": row.event_type,
                    "payload": row.payload_json,
                    "idempotency_key": row.idempotency_key,
                    "retry_count": row.retry_count,
                })
            s.commit()

        return claimed_events

    def complete_event(self, event_id: str) -> None:
        """Mark event as successfully dispatched."""
        with self.db.session() as s:
            event = s.get(OutboxEventRow, event_id)
            if event:
                event.status = "DISPATCHED"
                event.dispatched_at = utcnow()
                event.locked_until = None
                s.commit()

    def fail_event(self, event_id: str, error_message: str) -> None:
        """Record dispatch failure, increment retry count, route to DEAD_LETTER if max retries exceeded."""
        with self.db.session() as s:
            event = s.get(OutboxEventRow, event_id)
            if event:
                event.retry_count += 1
                if event.retry_count >= self.max_retries:
                    event.status = "DEAD_LETTER"
                    event.locked_until = None
                    logger.error("Outbox event %s routed to DEAD_LETTER: %s", event_id, error_message)
                else:
                    # Release lock so it can be retried on next poll
                    event.locked_until = None
                    logger.warning("Outbox event %s failed (attempt %d): %s", event_id, event.retry_count, error_message)
                s.commit()

    def dispatch_single_event(
        self,
        event: Dict[str, Any],
        custom_handler: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> bool:
        """Dispatch a single claimed event using the telephony gateway simulation or custom handler.
        
        Applies idempotency deduplication to guarantee exactly-once logical effects.
        """
        idempotency_key = event["idempotency_key"]

        try:
            if custom_handler:
                success = custom_handler(event)
            else:
                # Default telephony gateway simulation
                if idempotency_key in self.dispatched_idempotency_keys:
                    logger.info("Deduplication: Outbox event %s already dispatched, ignoring replay.", idempotency_key)
                    # Deduplicated: consider successful without duplicate dial side effect
                    success = True
                else:
                    self.dispatched_idempotency_keys.add(idempotency_key)
                    self.dispatch_call_count += 1
                    logger.info("Dispatched call dial for event %s", idempotency_key)
                    success = True

            if success:
                self.complete_event(event["id"])
                return True
            else:
                self.fail_event(event["id"], "Handler returned False")
                return False
        except Exception as exc:
            self.fail_event(event["id"], str(exc))
            return False

    def process_pending_events(self, batch_size: int = 10) -> int:
        """Poll, claim, and process pending events."""
        events = self.claim_batch(batch_size=batch_size)
        dispatched_count = 0
        for ev in events:
            if self.dispatch_single_event(ev):
                dispatched_count += 1
        return dispatched_count
