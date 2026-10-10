"""Sandbox Telephony Adapter for deterministic integration and contract testing."""

import hmac
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

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


class SandboxTelephonyProvider(TelephonyProvider):
    """Sandbox provider that simulates real telephony semantics with deterministic behavior.
    
    Used strictly in integration testing, CI/CD, and local sandbox verification.
    Never fabricates customer progress in real production runtime.
    """

    def __init__(self, webhook_secret: str = "sandbox-telephony-secret-v1") -> None:
        self.webhook_secret = webhook_secret
        self.calls: Dict[str, Dict[str, Any]] = {}
        self.transfer_supported: bool = True
        self.force_failure: bool = False
        self.last_error: Optional[str] = None
        self._provider_name = "sandbox"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def is_configured(self) -> bool:
        return True

    async def initiate_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        if self.force_failure:
            return TelephonyCallResult(
                success=False,
                call_id=request.call_id,
                provider_call_sid="",
                status=TelephonyCallStatus.FAILED,
                message="Simulated upstream telephony gateway rejection",
                error_code="GATEWAY_UNAVAILABLE",
            )

        sid = f"SANDBOX-SID-{uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)
        record = {
            "provider_call_sid": sid,
            "call_id": request.call_id,
            "customer_ref": request.customer_ref,
            "to_phone": request.to_phone,
            "from_phone": request.from_phone,
            "status": TelephonyCallStatus.INITIATED,
            "created_at": now,
            "updated_at": now,
            "transferred_to": None,
        }
        self.calls[sid] = record

        return TelephonyCallResult(
            success=True,
            call_id=request.call_id,
            provider_call_sid=sid,
            status=TelephonyCallStatus.INITIATED,
            message="Outbound call queued with sandbox telephony gateway",
            created_at=now,
            raw_response={"sid": sid, "status": "initiated"},
        )

    async def get_call_status(self, provider_call_sid: str) -> TelephonyCallResult:
        record = self.calls.get(provider_call_sid)
        if not record:
            return TelephonyCallResult(
                success=False,
                call_id="",
                provider_call_sid=provider_call_sid,
                status=TelephonyCallStatus.FAILED,
                message="Call SID not found in sandbox registry",
                error_code="NOT_FOUND",
            )
        return TelephonyCallResult(
            success=True,
            call_id=record["call_id"],
            provider_call_sid=provider_call_sid,
            status=record["status"],
            created_at=record["created_at"],
            raw_response=record,
        )

    async def hangup_call(self, provider_call_sid: str) -> bool:
        record = self.calls.get(provider_call_sid)
        if not record:
            return False
        record["status"] = TelephonyCallStatus.COMPLETED
        record["updated_at"] = datetime.now(timezone.utc)
        return True

    async def transfer_to_agent(
        self, provider_call_sid: str, agent_phone: str, agent_id: str
    ) -> TelephonyTransferResult:
        record = self.calls.get(provider_call_sid)
        if not record:
            return TelephonyTransferResult(
                success=False,
                call_id="",
                target_agent_id=agent_id,
                status="FAILED",
                message="Call SID not found",
                error_code="CALL_NOT_FOUND",
            )

        if not self.transfer_supported:
            return TelephonyTransferResult(
                success=False,
                call_id=record["call_id"],
                target_agent_id=agent_id,
                status="UNSUPPORTED",
                message="Agent bridging is not supported on this sandbox trunk",
                error_code="TRANSFER_UNSUPPORTED",
            )

        record["transferred_to"] = agent_id
        record["updated_at"] = datetime.now(timezone.utc)
        return TelephonyTransferResult(
            success=True,
            call_id=record["call_id"],
            target_agent_id=agent_id,
            status="BRIDGED",
            message=f"Call successfully transferred to agent {agent_id} ({agent_phone})",
        )

    def generate_signature(self, payload_bytes: bytes) -> str:
        """Helper to generate valid HMAC-SHA256 signature for test webhooks."""
        return hmac.new(
            self.webhook_secret.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()

    def verify_webhook_signature(
        self, payload_bytes: bytes, headers: Dict[str, str]
    ) -> bool:
        sig = headers.get("X-Telephony-Signature") or headers.get("x-telephony-signature")
        if not sig:
            return False
        expected = self.generate_signature(payload_bytes)
        return hmac.compare_digest(sig, expected)

    def parse_webhook_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> TelephonyWebhookEvent:
        sid = payload.get("provider_call_sid") or payload.get("CallSid", "")
        call_id = payload.get("call_id") or ""
        status_str = payload.get("status") or payload.get("CallStatus", "COMPLETED")

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
        }
        status = status_map.get(status_str.lower(), TelephonyCallStatus.COMPLETED)

        # Update in-memory sandbox state if present
        if sid in self.calls:
            self.calls[sid]["status"] = status
            self.calls[sid]["updated_at"] = datetime.now(timezone.utc)

        ts = datetime.now(timezone.utc)
        if "timestamp" in payload:
            try:
                ts = datetime.fromisoformat(payload["timestamp"])
            except Exception:
                pass

        return TelephonyWebhookEvent(
            event_id=payload.get("event_id", f"EVT-{uuid4().hex[:8].upper()}"),
            event_type=payload.get("event_type", "call.status"),
            call_id=call_id or (self.calls.get(sid, {}).get("call_id", "")),
            provider_call_sid=sid,
            status=status,
            timestamp=ts,
            duration_sec=payload.get("duration_sec") or payload.get("CallDuration"),
            recording_url=payload.get("recording_url") or payload.get("RecordingUrl"),
            disposition=payload.get("disposition"),
            raw_payload=payload,
        )

    async def health_check(self) -> TelephonyHealthStatus:
        if self.force_failure:
            return TelephonyHealthStatus(
                provider_name=self._provider_name,
                status=TelephonyProviderStatus.AUTH_FAILED,
                is_live=False,
                last_health_check=datetime.now(timezone.utc),
                last_error=self.last_error or "Sandbox simulated gateway failure",
            )
        return TelephonyHealthStatus(
            provider_name=self._provider_name,
            status=TelephonyProviderStatus.HEALTHY,
            is_live=True,
            configured_phone_number="+91 1800 200 4400 (Sandbox)",
            last_health_check=datetime.now(timezone.utc),
            details={"calls_active": len(self.calls), "mode": "sandbox"},
        )
