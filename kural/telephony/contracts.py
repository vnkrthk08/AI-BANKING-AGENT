"""Vendor-neutral Telephony Provider contracts and event schemas."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TelephonyCallStatus(str, Enum):
    QUEUED = "QUEUED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BUSY = "BUSY"
    NO_ANSWER = "NO_ANSWER"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TelephonyProviderStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIG_INCOMPLETE = "CONFIG_INCOMPLETE"
    CONNECTED = "CONNECTED"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AUTH_FAILED = "AUTH_FAILED"


@dataclass
class TelephonyCallRequest:
    to_phone: str
    from_phone: str
    customer_ref: str
    call_id: str
    campaign_id: Optional[str] = None
    callback_id: Optional[str] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None


@dataclass
class TelephonyCallResult:
    success: bool
    call_id: str
    provider_call_sid: str
    status: TelephonyCallStatus
    message: str = ""
    error_code: Optional[str] = None
    created_at: Optional[datetime] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TelephonyTransferResult:
    success: bool
    call_id: str
    target_agent_id: str
    status: str
    message: str = ""
    error_code: Optional[str] = None


@dataclass
class TelephonyWebhookEvent:
    event_id: str
    event_type: str
    call_id: str
    provider_call_sid: str
    status: TelephonyCallStatus
    timestamp: datetime
    duration_sec: Optional[int] = None
    recording_url: Optional[str] = None
    disposition: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TelephonyHealthStatus:
    provider_name: str
    status: TelephonyProviderStatus
    is_live: bool
    configured_phone_number: Optional[str] = None
    last_health_check: Optional[datetime] = None
    last_error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class TelephonyProvider(ABC):
    """Abstract vendor-neutral interface for physical telephony integrations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the telephony provider (e.g., 'exotel', 'sandbox', 'disabled')."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the provider has necessary credentials and configuration to dial calls."""
        pass

    @abstractmethod
    async def initiate_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        """Initiate an outbound telephone call."""
        pass

    @abstractmethod
    async def get_call_status(self, provider_call_sid: str) -> TelephonyCallResult:
        """Fetch real-time status of an active or completed call."""
        pass

    @abstractmethod
    async def hangup_call(self, provider_call_sid: str) -> bool:
        """Terminate an active call."""
        pass

    @abstractmethod
    async def transfer_to_agent(
        self, provider_call_sid: str, agent_phone: str, agent_id: str
    ) -> TelephonyTransferResult:
        """Bridge or transfer an active call to a human banking representative."""
        pass

    @abstractmethod
    def verify_webhook_signature(
        self, payload_bytes: bytes, headers: Dict[str, str]
    ) -> bool:
        """Verify the cryptographic authenticity of an incoming provider webhook."""
        pass

    @abstractmethod
    def parse_webhook_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> TelephonyWebhookEvent:
        """Parse raw provider webhook into standardized TelephonyWebhookEvent."""
        pass

    @abstractmethod
    async def health_check(self) -> TelephonyHealthStatus:
        """Check provider connectivity, authentication, and capability status."""
        pass
