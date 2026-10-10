from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
    return_state: State | None = None
    repetition_count: int = 0
    known_customer_facts: dict[str, Any] = field(default_factory=dict)
    unknown_required_fields: list[str] = field(default_factory=list)
    active_question: str | None = None
    active_issue: dict[str, Any] | None = None
    conversation_summary: str = ""
    recent_relevant_turns: list[dict[str, str]] = field(default_factory=list)
    detour_depth: int = 0
    callback_readback: str | None = None
    callback_info: dict[str, Any] = field(default_factory=dict)

    @property
    def current_state(self) -> State:
        return self.state

    @current_state.setter
    def current_state(self, new_state: State) -> None:
        self.state = new_state


