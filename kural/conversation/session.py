"""Domain session snapshot used by the FSM and repository boundary."""

from dataclasses import dataclass
from datetime import datetime

from kural.models import State


@dataclass
class Conversation:
    session_id: str
    customer_ref: str
    state: State
    created_at: datetime
    updated_at: datetime
    turn_order: int = 0
    case_id: str | None = None
    callback_id: str | None = None

