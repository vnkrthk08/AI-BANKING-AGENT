"""Safe transcript representation."""

from __future__ import annotations

import re

from kural.policy.safety import redact
from kural.privacy.redactor import redact_sensitive_data

_EXPLICIT_NAME = re.compile(
    r"\b(?P<prefix>my name is|name is|i am|i'm|this is)\s+"
    r"(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)


def _redact_explicit_name(text: str) -> str:
    return _EXPLICIT_NAME.sub(lambda match: f"{match.group('prefix')} [REDACTED NAME]", text)


def safe_transcript(text: str) -> str:
    redaction = redact_sensitive_data(text)
    name_cleaned = _redact_explicit_name(redaction.redacted_text)
    return name_cleaned
