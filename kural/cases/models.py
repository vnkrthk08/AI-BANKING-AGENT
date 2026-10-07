"""Persistence-independent case and callback domain records."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SupportCase:
    case_id: str
    session_id: str
    customer_ref: str
    category: str
    description: str
    status: str
    callback_requested: bool
    created_at: datetime
    updated_at: datetime
    raw_customer_quote: str = ""


@dataclass(frozen=True)
class CallbackRequest:
    callback_id: str
    session_id: str
    case_id: str | None
    requested_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
