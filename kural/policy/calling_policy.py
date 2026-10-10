"""TRAI/TCCCPR Regulatory Calling Policy Engine and Data Boundary Enforcement for Phase 4."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from zoneinfo import ZoneInfo
from sqlalchemy import select, update

from kural.persistence.database import Database
from kural.persistence.models import CallbackRow, CampaignContactRow, CustomerRow

logger = logging.getLogger("kural.policy.calling")

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def is_sunday(dt: datetime | None = None) -> bool:
    """Return True if the given datetime (in Asia/Kolkata timezone) is Sunday."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(KOLKATA_TZ)
    return ist_dt.weekday() == 6


def is_within_calling_hours(dt: datetime | None = None) -> bool:
    """Return True if the given datetime (in Asia/Kolkata timezone) falls within the bank's
    configured calling window (default 09:00–19:00 IST; see KURAL_CALLING_WINDOW_*_HOUR).
    """
    from kural.config import get_settings

    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(KOLKATA_TZ)
    settings = get_settings()
    return settings.calling_window_start_hour <= ist_dt.hour < settings.calling_window_end_hour


def configured_holidays() -> set[date]:
    """Bank holidays from the resolver calendar plus KURAL_HOLIDAYS (comma-separated YYYY-MM-DD)."""
    import os
    from kural.scheduling.resolver import HOLIDAY_CALENDAR

    holidays = set(HOLIDAY_CALENDAR)
    for raw in os.getenv("KURAL_HOLIDAYS", "").split(","):
        raw = raw.strip()
        if raw:
            try:
                holidays.add(date.fromisoformat(raw))
            except ValueError:
                logger.warning("Ignoring malformed KURAL_HOLIDAYS entry")
    return holidays


def is_holiday(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KOLKATA_TZ).date() in configured_holidays()


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str
    message: str

    def __bool__(self) -> bool:
        return self.allowed


ALLOW = PolicyDecision(True, "ALLOWED", "Permitted by calling policy")


def evaluate_contact_time(dt: datetime, now: datetime | None = None, *, min_lead_minutes: int = 0) -> PolicyDecision:
    """Is ``dt`` an acceptable moment to place a customer call (window, Sunday, holiday, not past)?"""
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt < now + timedelta(minutes=min_lead_minutes) - timedelta(seconds=60):
        return PolicyDecision(False, "IN_PAST", "The requested time has already passed.")
    if is_sunday(dt):
        return PolicyDecision(False, "SUNDAY", "Customer calls are not placed on Sundays.")
    if is_holiday(dt):
        return PolicyDecision(False, "HOLIDAY", "Customer calls are not placed on bank holidays.")
    if not is_within_calling_hours(dt):
        from kural.config import get_settings
        s = get_settings()
        return PolicyDecision(
            False, "OUTSIDE_WINDOW",
            f"Customer calls are only placed between {s.calling_window_start_hour:02d}:00 and "
            f"{s.calling_window_end_hour:02d}:00 IST.",
        )
    return ALLOW


def next_permitted_slot(after: datetime, hour: int | None = None) -> datetime:
    """Earliest whole-hour slot at or after ``after`` (optionally at ``hour`` IST) that policy allows."""
    from kural.config import get_settings

    settings = get_settings()
    local = after.astimezone(KOLKATA_TZ).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(24 * 21):
        if hour is not None and local.hour != hour:
            local += timedelta(hours=1)
            continue
        candidate = local.astimezone(timezone.utc)
        if (settings.calling_window_start_hour <= local.hour < settings.calling_window_end_hour
                and not is_sunday(candidate) and not is_holiday(candidate)):
            return candidate
        local += timedelta(hours=1)
    raise RuntimeError("No permitted calling slot found within three weeks")


class CallingPolicyEngine:
    """Enforces TRAI/TCCCPR regulatory calling windows, DND fail-closed validation,
    real-time opt-out precedence, and bank speech data boundaries.
    """

    POLICY_VERSION = "v1.0.2"

    def __init__(self, dnd_timeout_sec: float = 2.0) -> None:
        self.dnd_timeout_sec = dnd_timeout_sec
        # Locally suppressed numbers (opt-outs captured during calls). The national NCPR
        # registry scrub is an external integration; customer.dnd_status carries its result.
        self._dnd_numbers: set[str] = set()

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
