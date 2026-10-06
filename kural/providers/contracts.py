"""Provider interfaces kept separate from KURAL decisions."""

from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any, Protocol

from kural.providers.schemas import IntentProposal


class STTProvider(Protocol):
    def transcribe(
        self, audio: bytes, *, filename: str = "customer.webm", content_type: str = "audio/webm",
    ) -> "Transcription": ...


class RealtimeSTTSession(Protocol):
    async def send_audio(self, pcm16_mono: bytes) -> None: ...
    async def receive_event(self) -> Any: ...


class RealtimeSTTProvider(Protocol):
    def connect(self) -> Any: ...


@dataclass(frozen=True)
class Transcription:
    text: str
    language_code: str | None = None


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def classify(self, text: str) -> IntentProposal: ...


class TTSProvider(Protocol):
    def stream(self, text: str) -> AsyncIterator[bytes]: ...

    def stream_realtime(self, text: str) -> AsyncIterator[bytes]: ...


class TelephonyProvider(Protocol):
    def start_call(self, destination: str) -> str: ...
    def end_call(self, call_id: str) -> None: ...

