"""TRAI/TCCCPR Regulatory Calling Policy Engine and Data Boundary Enforcement for Phase 4."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select, update

from kural.persistence.database import Database
from kural.persistence.models import CallbackRow, CampaignContactRow, CustomerRow

logger = logging.getLogger("kural.policy.calling")


class CallingPolicyEngine:
    """Enforces TRAI/TCCCPR regulatory calling windows, DND fail-closed validation,
    real-time opt-out precedence, and bank speech data boundaries.
    """

    POLICY_VERSION = "v1.0.2"

    def __init__(self, dnd_timeout_sec: float = 2.0) -> None:
        self.dnd_timeout_sec = dnd_timeout_sec
        # Internal simulated DND registry set
        self._dnd_numbers: set[str] = {"9876543210", "9876543299"}

    def add_dnd_number(self, phone: str) -> None:
        self._dnd_numbers.add(phone.strip())

    def evaluate_dnd_status(
        self,
        phone: str,
        simulate_timeout: bool = False,
    ) -> Tuple[bool, str]:
        """Evaluate telephone against National Do Not Call (DND) Registry.
        
        STRICT FAIL-CLOSED: Any timeout, unreachable registry, or ambiguous error
        blocks outbound dialing immediately.
        """
        if simulate_timeout:
            logger.warning("DND Registry request timed out after %.1fs. Failing closed.", self.dnd_timeout_sec)
            return False, "DND_REGISTRY_TIMEOUT_FAIL_CLOSED"

        normalized = phone.replace("+91", "").replace(" ", "").strip()
        if normalized in self._dnd_numbers:
            return False, "CUSTOMER_REGISTERED_DND"

        return True, "ALLOWED"

    def evaluate_calling_window(
        self,
        campaign_category: str,
        current_hour: int,
    ) -> Tuple[bool, str]:
        """Evaluate campaign calling windows.
        
        Promotional campaigns: strictly disabled for live calls until bank legal sign-off.
        Service campaigns: restricted to standard 08:00 to 21:00 window.
        """
        category = campaign_category.upper()
        if category == "PROMOTIONAL":
            return False, "PROMOTIONAL_CALLING_UNAPPROVED_FAIL_CLOSED"

        if category == "SERVICE":
            if not (8 <= current_hour < 21):
                return False, "CALLING_WINDOW_VIOLATION_FAIL_CLOSED"
            return True, "ALLOWED"

        return False, "UNKNOWN_CAMPAIGN_CATEGORY_FAIL_CLOSED"

    def apply_realtime_opt_out(
        self,
        customer_ref: str,
        database: Database,
    ) -> bool:
        """Real-time customer opt-out precedence during active voice calls.
        
        Instantly flags customer as DND, cancels pending callbacks, and removes from active campaigns.
        """
        with database.session() as s:
            cust = s.scalar(select(CustomerRow).where(CustomerRow.customer_ref == customer_ref))
            if cust:
                cust.dnd_status = True
                self.add_dnd_number(cust.phone)

            # Cancel active campaign contacts
            s.execute(
                update(CampaignContactRow)
                .where(CampaignContactRow.customer_ref == customer_ref)
                .values(status="OPTED_OUT")
            )

            # Cancel scheduled callbacks
            s.execute(
                update(CallbackRow)
                .where(CallbackRow.customer_ref == customer_ref, CallbackRow.status == "SCHEDULED")
                .values(status="CANCELLED")
            )

            s.commit()
            logger.info("Real-time opt-out processed: customer %s removed from all campaigns.", customer_ref)
            return True

    @staticmethod
    def validate_speech_processing_boundary(
        is_real_customer_session: bool,
        stt_provider_type: str,
        is_on_premise_certified: bool = False,
    ) -> bool:
        """Enforces invariant: Real customer voice sessions MUST NOT route to external cloud STT."""
        if is_real_customer_session:
            if stt_provider_type.lower() == "external_cloud" and not is_on_premise_certified:
                raise PermissionError(
                    "REAL_CUSTOMER_EXTERNAL_STT_FORBIDDEN: External cloud speech processing is strictly prohibited for real customer voice sessions without on-premises certification."
                )
        return True
