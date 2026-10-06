"""Shared typed conversation models."""

from enum import StrEnum
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class State(StrEnum):
    DISCLOSURE = "DISCLOSURE"
    IDENTITY_CHECK = "IDENTITY_CHECK"
    PERMISSION = "PERMISSION"
    APP_STATUS = "APP_STATUS"
    UPDATE_HELP = "UPDATE_HELP"
    ISSUE_CAPTURE = "ISSUE_CAPTURE"
    CASE_CREATION = "CASE_CREATION"
    CALLBACK_BOOKING = "CALLBACK_BOOKING"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    OPT_OUT = "OPT_OUT"
    FRAUD_ESCALATION = "FRAUD_ESCALATION"
    CLOSING = "CLOSING"
    ENDED = "ENDED"


class Intent(StrEnum):
    WANTS_HUMAN = "WANTS_HUMAN"
    FRAUD_REPORT = "FRAUD_REPORT"
    OPT_OUT = "OPT_OUT"
    ASKS_IF_AI = "ASKS_IF_AI"
    ASKS_IDENTITY = "ASKS_IDENTITY"
    TRUST_CONCERN = "TRUST_CONCERN"
    SENSITIVE_DATA = "SENSITIVE_DATA"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    ABUSE = "ABUSE"
    SILENCE = "SILENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LANGUAGE_SWITCH = "LANGUAGE_SWITCH"
    AFFIRM = "AFFIRM"
    NEGATE = "NEGATE"
    BUSY = "BUSY"
    APP_INSTALLED = "APP_INSTALLED"
    APP_NOT_INSTALLED = "APP_NOT_INSTALLED"
    UPDATE_SUCCESS = "UPDATE_SUCCESS"
    UPDATE_FAILURE = "UPDATE_FAILURE"
    # Provider-facing name for the same customer issue; UPDATE_FAILURE remains
    # supported for existing clients and deterministic intent rules.
    APP_UPDATE_ISSUE = "APP_UPDATE_ISSUE"
    CALLBACK = "CALLBACK"
    OTHER = "OTHER"


class Action(StrEnum):
    """KURAL-owned side effects. Provider output can never name executable tools."""

    NO_OP = "no_op"
    END_SESSION = "end_session"
    CREATE_APP_UPDATE_CASE = "create_app_update_case"
    REQUEST_CALLBACK = "request_callback"


class TurnRequest(BaseModel):
    text: str = Field(max_length=2000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requested_at: datetime | None = None


class SessionCreateRequest(BaseModel):
    customer_ref: Literal["CUST001", "demo-001", "demo-002"] = "demo-001"


class TurnResponse(BaseModel):
    session_id: str
    state: State
    intent: Intent
    response: str
    ended: bool
    case_id: str | None = None
    callback_id: str | None = None
    policy_decision: Literal["ALLOWED", "BLOCKED"] = "ALLOWED"
    sanitized_user_text: str = ""


class SessionResponse(BaseModel):
    session_id: str
    state: State
    response: str
    customer_ref: str = "demo-001"


class VoiceTurnResponse(BaseModel):
    session_id: str
    transcript: str
    language_code: str | None = None
    intent: Intent
    state: State
    response: str
    ended: bool
    case_id: str | None = None
    callback_id: str | None = None
    policy_decision: Literal["ALLOWED", "BLOCKED"]
    audio_base64: str | None = None
    audio_content_type: str = "audio/mpeg"
    tts_error: str | None = None

