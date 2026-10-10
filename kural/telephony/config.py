"""Telephony Provider Configuration and Factory."""

import os
from typing import Optional

from kural.telephony.contracts import TelephonyProvider, TelephonyHealthStatus, TelephonyProviderStatus
from kural.telephony.sandbox import SandboxTelephonyProvider
from kural.telephony.exotel import ExotelTelephonyProvider


class DisabledTelephonyProvider(TelephonyProvider):
    """Fallback provider when physical telephony is disabled or unconfigured."""

    @property
    def provider_name(self) -> str:
        return "disabled"

    @property
    def is_configured(self) -> bool:
        return False

    async def initiate_call(self, request):
        from kural.telephony.contracts import TelephonyCallResult, TelephonyCallStatus
        return TelephonyCallResult(
            success=False,
            call_id=request.call_id,
            provider_call_sid="",
            status=TelephonyCallStatus.FAILED,
            message="Physical telephony integration is disabled. Browser voice is available.",
            error_code="TELEPHONY_DISABLED",
        )

    async def get_call_status(self, provider_call_sid: str):
        from kural.telephony.contracts import TelephonyCallResult, TelephonyCallStatus
        return TelephonyCallResult(
            success=False,
            call_id="",
            provider_call_sid=provider_call_sid,
            status=TelephonyCallStatus.FAILED,
            message="Telephony disabled",
            error_code="TELEPHONY_DISABLED",
        )

    async def hangup_call(self, provider_call_sid: str) -> bool:
        return False

    async def transfer_to_agent(self, provider_call_sid: str, agent_phone: str, agent_id: str):
        from kural.telephony.contracts import TelephonyTransferResult
        return TelephonyTransferResult(
            success=False,
            call_id="",
            target_agent_id=agent_id,
            status="DISABLED",
            message="Agent transfer requires an active telephony trunk",
            error_code="TELEPHONY_DISABLED",
        )

    def verify_webhook_signature(self, payload_bytes: bytes, headers) -> bool:
        return False

    def parse_webhook_event(self, payload, headers):
        from datetime import datetime, timezone
        from kural.telephony.contracts import TelephonyWebhookEvent, TelephonyCallStatus
        return TelephonyWebhookEvent(
            event_id="disabled",
            event_type="disabled",
            call_id="",
            provider_call_sid="",
            status=TelephonyCallStatus.FAILED,
            timestamp=datetime.now(timezone.utc),
        )

    async def health_check(self) -> TelephonyHealthStatus:
        from datetime import datetime, timezone
        return TelephonyHealthStatus(
            provider_name="disabled",
            status=TelephonyProviderStatus.NOT_CONFIGURED,
            is_live=False,
            last_health_check=datetime.now(timezone.utc),
            last_error="TELEPHONY_PROVIDER set to disabled or not configured",
            details={
                "instructions": "Set TELEPHONY_PROVIDER=exotel or TELEPHONY_PROVIDER=sandbox in .env"
            },
        )


_active_telephony_provider: Optional[TelephonyProvider] = None


def get_telephony_provider() -> TelephonyProvider:
    """Factory to retrieve or instantiate the configured TelephonyProvider."""
    global _active_telephony_provider
    if _active_telephony_provider is not None:
        return _active_telephony_provider

    provider_type = os.environ.get("TELEPHONY_PROVIDER", "").lower().strip()

    if provider_type == "exotel":
        _active_telephony_provider = ExotelTelephonyProvider()
    elif provider_type == "sandbox":
        _active_telephony_provider = SandboxTelephonyProvider()
    elif provider_type in ("", "disabled", "none"):
        # If EXOTEL_API_KEY is present, auto-detect Exotel
        if os.environ.get("EXOTEL_API_KEY") and os.environ.get("EXOTEL_ACCOUNT_SID"):
            _active_telephony_provider = ExotelTelephonyProvider()
        else:
            _active_telephony_provider = DisabledTelephonyProvider()
    else:
        _active_telephony_provider = DisabledTelephonyProvider()

    return _active_telephony_provider


def set_telephony_provider(provider: TelephonyProvider) -> None:
    """Explicitly set provider for testing and sandboxes."""
    global _active_telephony_provider
    _active_telephony_provider = provider
