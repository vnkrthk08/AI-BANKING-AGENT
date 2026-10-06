"""Sensitive input screening, redaction, and safe action decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kural.models import Action, State
from kural.privacy.redactor import (
    RedactionResult,
    detect_sensitive_partial,
    is_luhn_valid,
    normalise_spoken_digits,
    redact_sensitive_data,
)


SENSITIVE_LABEL = re.compile(r"\b(?:otp|one[- ]time password|pin|mpin|password|cvv|cvc)\b", re.I)


@dataclass(frozen=True)
class SafetyResult:
    blocked: bool
    redacted_text: str
    reason: str | None = None
    sensitive_types: list[str] = field(default_factory=list)
    sensitive_count: int = 0


def inspect_input(text: str) -> SafetyResult:
    """Screen text for sensitive authentication data."""
    redaction = redact_sensitive_data(text)
    return SafetyResult(
        blocked=redaction.sensitive_present,
        redacted_text=redaction.redacted_text,
        reason="sensitive_authentication_data" if redaction.sensitive_present else None,
        sensitive_types=redaction.sensitive_types,
        sensitive_count=redaction.sensitive_count,
    )


def redact(text: str) -> str:
    """Redact standalone codes and longer numeric identifiers, including spaced PANs."""
    return re.sub(r"(?<!\d)(?:\d[ -]?){2,18}\d(?!\d)", "[REDACTED]", text)


def authorize(action: Action, source: State, target: State) -> bool:
    """Authorize prototype actions only in the FSM states that own them."""
    if source in {State.OPT_OUT, State.FRAUD_ESCALATION, State.HUMAN_ESCALATION, State.ENDED}:
        return False
    if action == Action.NO_OP:
        return target == source or target in {
            State.IDENTITY_CHECK, State.PERMISSION, State.APP_STATUS, State.UPDATE_HELP,
            State.ISSUE_CAPTURE, State.CALLBACK_BOOKING,
        }
    if action == Action.END_SESSION:
        return target in {
            State.CLOSING, State.ENDED, State.OPT_OUT, State.FRAUD_ESCALATION,
            State.HUMAN_ESCALATION,
        }
    if action == Action.CREATE_APP_UPDATE_CASE:
        return source == State.ISSUE_CAPTURE and target == State.CASE_CREATION
    if action == Action.REQUEST_CALLBACK:
        return (source == State.CALLBACK_BOOKING and target == State.ENDED) or (
            source in {State.IDENTITY_CHECK, State.PERMISSION} and target == State.CALLBACK_BOOKING
        ) or (
            source == State.ISSUE_CAPTURE and target == State.CASE_CREATION
        )
    return False
