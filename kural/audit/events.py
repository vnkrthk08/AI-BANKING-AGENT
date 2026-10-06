"""Minimal in-memory audit trail; sensitive authentication inputs are excluded."""

from datetime import datetime, timezone
from typing import Any

from kural.privacy.transcript import safe_transcript

STRUCTURAL_FIELDS = {
    "session_id", "case_id", "callback_id", "old", "new", "intent", "issue_type",
    "action", "decision",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return safe_transcript(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


class AuditLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, **fields: Any) -> None:
        # Audit is the final privacy boundary, even if callers use an unexpected field name.
        fields = {
            key: value if key in STRUCTURAL_FIELDS else _sanitize(value)
            for key, value in fields.items()
        }
        self.events.append({"event": event_type, "at": datetime.now(timezone.utc).isoformat(), **fields})

