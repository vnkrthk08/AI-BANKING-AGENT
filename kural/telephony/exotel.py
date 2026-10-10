"""Production-ready India-compatible Telephony Adapter (Exotel / Twilio compatible REST API)."""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

import httpx

from kural.telephony.contracts import (
    TelephonyCallRequest,
    TelephonyCallResult,
    TelephonyCallStatus,
    TelephonyHealthStatus,
    TelephonyProvider,
    TelephonyProviderStatus,
    TelephonyTransferResult,
    TelephonyWebhookEvent,
)

logger = logging.getLogger("kural.telephony.exotel")


class ExotelTelephonyProvider(TelephonyProvider):
    """Production telephony adapter for Exotel cloud telephony platform.
    
    Adheres strictly to the invariant:
    If credentials (API key, token, subdomain, caller ID) are missing,
    exposes truthful NOT_CONFIGURED status and prevents silent fake successes.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_token: Optional[str] = None,
        subdomain: Optional[str] = None,
        account_sid: Optional[str] = None,
        caller_id: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("EXOTEL_API_KEY", "")
        self.api_token = api_token or os.environ.get("EXOTEL_API_TOKEN", "")
        self.subdomain = subdomain or os.environ.get("EXOTEL_SUBDOMAIN", "api.exotel.com")
        self.account_sid = account_sid or os.environ.get("EXOTEL_ACCOUNT_SID", "")
        self.caller_id = caller_id or os.environ.get("EXOTEL_CALLER_ID", "")
        self.webhook_secret = webhook_secret or os.environ.get("EXOTEL_WEBHOOK_SECRET", "")
        self._last_error: Optional[str] = None

    @property
    def provider_name(self) -> str:
        return "exotel"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_token and self.account_sid and self.caller_id)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{self.account_sid}"

    async def initiate_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        if not self.is_configured:
            return TelephonyCallResult(
                success=False,
                call_id=request.call_id,
                provider_call_sid="",
                status=TelephonyCallStatus.FAILED,
                message="Exotel telephony provider is not configured. Real telephony credentials required.",
                error_code="PROVIDER_NOT_CONFIGURED",
            )

        app_id = os.environ.get("EXOTEL_APP_ID", "")
        if not app_id:
            return TelephonyCallResult(success=False, call_id=request.call_id, provider_call_sid="",
                                       status=TelephonyCallStatus.FAILED, error_code="PROVIDER_NOT_CONFIGURED",
                                       message="EXOTEL_APP_ID (the call flow connecting to the AVA voice bot) is not set.")
        endpoint = f"{self.base_url}/Calls/connect.json"
        from kural.config import get_settings
        settings = get_settings()
        data = {
            "From": request.to_phone,
            "CallerId": self.caller_id,
            "Url": f"http://my.exotel.com/{self.account_sid}/exoml/start_voice/{app_id}",
            "CallType": "trans",
            "CustomField": request.call_id,
            "TimeLimit": os.environ.get("EXOTEL_TIME_LIMIT_SEC", "900"),
            "StatusCallback": f"{settings.public_base_url}/api/v1/telephony/webhooks?token={settings.telephony_webhook_token}",
            "StatusCallbackContentType": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    endpoint,
                    data=data,
                    auth=(self.api_key, self.api_token),
                )
                if resp.status_code in (200, 201):
                    body = resp.json()
                    call_obj = body.get("Call", {})
                    sid = call_obj.get("Sid")
                    if not sid:
                        return TelephonyCallResult(success=False, call_id=request.call_id, provider_call_sid="",
                                                   status=TelephonyCallStatus.FAILED, error_code="GATEWAY_ERROR",
                                                   message="Exotel response did not include a call Sid")
                    return TelephonyCallResult(
                        success=True,
                        call_id=request.call_id,
                        provider_call_sid=sid,
                        status=TelephonyCallStatus.INITIATED,
                        message="Call initiated successfully with Exotel gateway",
                        created_at=datetime.now(timezone.utc),
                        raw_response=body,
                    )
                else:
                    self._last_error = f"HTTP {resp.status_code}"
                    return TelephonyCallResult(
                        success=False,
                        call_id=request.call_id,
                        provider_call_sid="",
                        status=TelephonyCallStatus.FAILED,
                        message=f"Exotel gateway rejected call request: {resp.status_code}",
                        error_code="GATEWAY_ERROR",
                        raw_response={"status_code": resp.status_code},
                    )
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("Failed to initiate Exotel call: %s", type(exc).__name__)
            return TelephonyCallResult(
                success=False,
                call_id=request.call_id,
                provider_call_sid="",
                status=TelephonyCallStatus.FAILED,
                message=f"Network error contacting Exotel: {type(exc).__name__}",
                error_code="CONNECTION_ERROR",
            )

    async def get_call_status(self, provider_call_sid: str) -> TelephonyCallResult:
        if not self.is_configured:
            return TelephonyCallResult(
                success=False,
                call_id="",
                provider_call_sid=provider_call_sid,
                status=TelephonyCallStatus.FAILED,
                message="Exotel provider not configured",
                error_code="PROVIDER_NOT_CONFIGURED",
            )

        endpoint = f"{self.base_url}/Calls/{provider_call_sid}.json"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(endpoint, auth=(self.api_key, self.api_token))
                if resp.status_code == 200:
                    body = resp.json()
                    call_obj = body.get("Call", {})
                    st_str = call_obj.get("Status", "").lower()
                    status = (
                        TelephonyCallStatus.IN_PROGRESS
                        if st_str == "in-progress"
                        else TelephonyCallStatus.COMPLETED
                        if st_str == "completed"
                        else TelephonyCallStatus.BUSY
                        if st_str == "busy"
                        else TelephonyCallStatus.NO_ANSWER
                        if st_str == "no-answer"
                        else TelephonyCallStatus.INITIATED
                    )
                    return TelephonyCallResult(
                        success=True,
                        call_id=call_obj.get("CustomField", ""),
                        provider_call_sid=provider_call_sid,
                        status=status,
                        raw_response=body,
                    )
                return TelephonyCallResult(
                    success=False,
                    call_id="",
                    provider_call_sid=provider_call_sid,
                    status=TelephonyCallStatus.FAILED,
                    message=f"Call status lookup failed: {resp.status_code}",
                    error_code="LOOKUP_ERROR",
                )
        except Exception as exc:
            return TelephonyCallResult(
                success=False,
                call_id="",
                provider_call_sid=provider_call_sid,
                status=TelephonyCallStatus.FAILED,
                message=str(exc),
                error_code="CONNECTION_ERROR",
            )

    async def hangup_call(self, provider_call_sid: str) -> bool:
        if not self.is_configured:
            return False
        endpoint = f"{self.base_url}/Calls/{provider_call_sid}.json"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    endpoint, data={"Status": "completed"}, auth=(self.api_key, self.api_token)
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def transfer_to_agent(
        self, provider_call_sid: str, agent_phone: str, agent_id: str
    ) -> TelephonyTransferResult:
        if not self.is_configured:
            return TelephonyTransferResult(
                success=False,
                call_id="",
                target_agent_id=agent_id,
                status="FAILED",
                message="Exotel telephony integration is not configured. Live transfer unavailable.",
                error_code="PROVIDER_NOT_CONFIGURED",
            )

        # Exotel's REST API has no endpoint to transfer an in-progress call; agent bridging must be
        # built into the Exotel call flow (Connect applet). Report that truthfully.
        return TelephonyTransferResult(
            success=False, call_id="", target_agent_id=agent_id, status="UNSUPPORTED",
            message="Live transfer is not available through the Exotel REST API; configure a Connect applet in the call flow.",
            error_code="TRANSFER_UNSUPPORTED",
        )

    def verify_webhook_signature(
        self, payload_bytes: bytes, headers: Dict[str, str]
    ) -> bool:
        if not self.webhook_secret:
            return False  # fail closed; the router also accepts the shared TELEPHONY_WEBHOOK_TOKEN
        sig = headers.get("X-Exotel-Signature") or headers.get("x-exotel-signature")
        if not sig:
            return False
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    def parse_webhook_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> TelephonyWebhookEvent:
        sid = payload.get("CallSid") or payload.get("Sid") or ""
        status_str = (payload.get("Status") or payload.get("CallStatus") or "").lower()
        call_id = payload.get("CustomField") or payload.get("call_id") or ""

        status_map = {
            "queued": TelephonyCallStatus.QUEUED,
            "initiated": TelephonyCallStatus.INITIATED,
            "ringing": TelephonyCallStatus.RINGING,
            "in-progress": TelephonyCallStatus.IN_PROGRESS,
            "completed": TelephonyCallStatus.COMPLETED,
            "busy": TelephonyCallStatus.BUSY,
            "no-answer": TelephonyCallStatus.NO_ANSWER,
            "failed": TelephonyCallStatus.FAILED,
            "cancelled": TelephonyCallStatus.CANCELLED,
            "canceled": TelephonyCallStatus.CANCELLED,
        }
        status = status_map.get(status_str, TelephonyCallStatus.FAILED)

        duration = None
        if "Duration" in payload or "CallDuration" in payload:
            try:
                duration = int(payload.get("Duration") or payload.get("CallDuration") or 0)
            except Exception:
                pass

        return TelephonyWebhookEvent(
            event_id=payload.get("EventId") or f"{sid}:{status_str}",
            event_type=payload.get("EventType", "call.status"),
            call_id=call_id,
            provider_call_sid=sid,
            status=status,
            timestamp=datetime.now(timezone.utc),
            duration_sec=duration,
            recording_url=payload.get("RecordingUrl"),
            disposition=payload.get("Disposition"),
            raw_payload=payload,
        )

    async def health_check(self) -> TelephonyHealthStatus:
        if not self.is_configured:
            return TelephonyHealthStatus(
                provider_name=self.provider_name,
                status=TelephonyProviderStatus.NOT_CONFIGURED,
                is_live=False,
                configured_phone_number=None,
                last_health_check=datetime.now(timezone.utc),
                last_error="Missing EXOTEL_API_KEY, EXOTEL_API_TOKEN, or EXOTEL_ACCOUNT_SID",
                details={
                    "configured": False,
                    "provider": "Exotel",
                    "setup_instructions": "Add EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_ACCOUNT_SID, EXOTEL_CALLER_ID to .env",
                },
            )

        # Check account endpoint
        endpoint = f"{self.base_url}.json"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(endpoint, auth=(self.api_key, self.api_token))
                if resp.status_code == 200:
                    return TelephonyHealthStatus(
                        provider_name=self.provider_name,
                        status=TelephonyProviderStatus.HEALTHY,
                        is_live=True,
                        configured_phone_number=self.caller_id,
                        last_health_check=datetime.now(timezone.utc),
                        details={"account_sid": self.account_sid, "caller_id": self.caller_id},
                    )
                elif resp.status_code in (401, 403):
                    return TelephonyHealthStatus(
                        provider_name=self.provider_name,
                        status=TelephonyProviderStatus.AUTH_FAILED,
                        is_live=False,
                        configured_phone_number=self.caller_id,
                        last_health_check=datetime.now(timezone.utc),
                        last_error=f"Authentication failed: HTTP {resp.status_code}",
                    )
                else:
                    return TelephonyHealthStatus(
                        provider_name=self.provider_name,
                        status=TelephonyProviderStatus.DEGRADED,
                        is_live=False,
                        configured_phone_number=self.caller_id,
                        last_health_check=datetime.now(timezone.utc),
                        last_error=f"Gateway responded with status {resp.status_code}",
                    )
        except Exception as exc:
            return TelephonyHealthStatus(
                provider_name=self.provider_name,
                status=TelephonyProviderStatus.DEGRADED,
                is_live=False,
                configured_phone_number=self.caller_id,
                last_health_check=datetime.now(timezone.utc),
                last_error=str(exc),
            )
