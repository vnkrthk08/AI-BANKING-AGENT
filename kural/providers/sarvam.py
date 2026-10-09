"""Sarvam speech adapters. Provider SDK details stay outside KURAL's engine."""

from __future__ import annotations

import os
import base64
import asyncio
from io import BytesIO
import time
from typing import Any
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from kural.providers.contracts import Transcription


class SarvamConfigurationError(RuntimeError):
    """Sarvam is not configured or its SDK is unavailable."""


class SarvamSTTAdapter:
    provider_type = "external_cloud"
    is_on_premise_certified = False
    model_name = "saaras:v4"
    mode = "transcribe"

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise SarvamConfigurationError("SARVAM_API_KEY is not configured")
            try:
                from sarvamai import SarvamAI
            except ImportError as error:
                raise SarvamConfigurationError("The sarvamai SDK is not installed") from error
            self._client = SarvamAI(api_subscription_key=self._api_key)
        return self._client

    def transcribe(
        self, audio: bytes, *, filename: str = "customer.webm", content_type: str = "audio/webm",
    ) -> Transcription:
        response = self._get_client().speech_to_text.transcribe(
            file=(filename, BytesIO(audio), content_type),
            model=self.model_name,
            mode=self.mode,
            request_options={"max_retries": 0},
        )
        transcript = getattr(response, "transcript", None)
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError("Sarvam returned an empty transcript")
        return Transcription(
            text=transcript.strip(),
            language_code=getattr(response, "language_code", None),
        )


class SarvamRealtimeSTTSession:
    """Provider-neutral operations over Sarvam's realtime socket."""

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket

    async def send_audio(self, pcm16_mono: bytes) -> None:
        from sarvamai import RealtimeAudioInput

        await self._websocket.send_realtime_audio_input(
            RealtimeAudioInput(audio=base64.b64encode(pcm16_mono).decode("ascii")),
        )

    async def receive_event(self) -> Any:
        return await self._websocket.recv()

    async def end(self) -> None:
        from sarvamai import RealtimeEnd

        await self._websocket.send_realtime_end(RealtimeEnd())


class SarvamRealtimeSTTAdapter:
    """Realtime Saaras adapter; credentials and SDK types stay server-side."""

    provider_type = "external_cloud"
    is_on_premise_certified = False
    model_name = "saaras:v4"
    language_code = "en-IN"

    def __init__(
        self,
        api_key: str | None = None,
        client: Any | None = None,
        threshold: str | None = None,
        min_speech_duration_ms: str | None = None,
    ) -> None:
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._client = client
        self.threshold = threshold or os.getenv("SARVAM_VAD_THRESHOLD", "0.65")
        self.min_speech_duration_ms = min_speech_duration_ms or os.getenv("SARVAM_VAD_MIN_SPEECH_DURATION_MS", "350")

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise SarvamConfigurationError("SARVAM_API_KEY is not configured")
            try:
                from sarvamai import AsyncSarvamAI
            except ImportError as error:
                raise SarvamConfigurationError("The sarvamai SDK is not installed") from error
            self._client = AsyncSarvamAI(api_subscription_key=self._api_key, timeout=30)
        return self._client

    @asynccontextmanager
    async def connect(self):
        async with self._get_client().speech_to_text_realtime_streaming.connect(
            language_code=self.language_code,
            model=self.model_name,
            stream_type="fast",
            mode="transcribe",
            endpointing="vad",
            encoding="linear16",
            sample_rate="16000",
            threshold=self.threshold,
            prefix_padding_ms="300",
            silence_duration_ms="600",
            min_speech_duration_ms=self.min_speech_duration_ms,
            request_options={"max_retries": 0},
        ) as websocket:
            yield SarvamRealtimeSTTSession(websocket)

    async def close(self) -> None:
        close = getattr(self._client, "close", None) or getattr(self._client, "aclose", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


class SarvamTTSAdapter:
    model_name = "bulbul:v3"
    language_code = "en-IN"
    content_type = "audio/mpeg"
    realtime_content_type = "audio/pcm;rate=24000;channels=1"
    realtime_sample_rate = 24000
    connect_timeout_seconds = 12
    operation_timeout_seconds = 40
    reusable_idle_seconds = 45

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._client = client
        self._connection_contexts: dict[str, Any] = {}
        self._websockets: dict[str, Any] = {}
        self._connection_locks = {"mp3": asyncio.Lock(), "linear16": asyncio.Lock()}
        self._last_used: dict[str, float] = {}

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise SarvamConfigurationError("SARVAM_API_KEY is not configured")
            try:
                from sarvamai import AsyncSarvamAI
            except ImportError as error:
                raise SarvamConfigurationError("The sarvamai SDK is not installed") from error
            self._client = AsyncSarvamAI(api_subscription_key=self._api_key, timeout=self.operation_timeout_seconds)
        return self._client

    async def _open_connection(self, codec: str) -> None:
        client = self._get_client()
        context = client.text_to_speech_streaming.connect(
            model=self.model_name,
            send_completion_event="true",
            request_options={"timeout_in_seconds": self.connect_timeout_seconds, "max_retries": 0},
        )
        websocket = await asyncio.wait_for(
            context.__aenter__(), timeout=self.connect_timeout_seconds,
        )
        try:
            await asyncio.wait_for(
                websocket.configure(
                    target_language_code=self.language_code,
                    speaker="shubh",
                    pace=1.0,
                    speech_sample_rate=24000,
                    enable_preprocessing=True,
                    output_audio_codec=codec,
                    output_audio_bitrate="128k",
                    min_buffer_size=30,
                    max_chunk_length=120,
                ),
                timeout=self.connect_timeout_seconds,
            )
        except BaseException:
            await context.__aexit__(None, None, None)
            raise
        self._connection_contexts[codec] = context
        self._websockets[codec] = websocket
        self._last_used[codec] = time.monotonic()

    async def _ensure_connection(self, codec: str) -> None:
        ws = self._websockets.get(codec)
        underlying = getattr(ws, "_websocket", ws)
        is_open = ws is not None and getattr(underlying, "open", True) and not getattr(underlying, "closed", False)
        if is_open and time.monotonic() - self._last_used.get(codec, 0) < self.reusable_idle_seconds:
            return
        await self._reset_connection(codec)
        last_error: Exception | None = None
        # Reconnect only before submitting text, so retries cannot duplicate speech generation.
        for _ in range(2):
            try:
                await self._open_connection(codec)
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                last_error = error
                await self._reset_connection(codec)
        raise SarvamConfigurationError("Sarvam TTS WebSocket connection failed") from last_error

    async def prewarm(self, codec: str = "linear16") -> None:
        """Pre-warm the realtime WebSocket connection under lock to eliminate first-turn setup lag."""
        try:
            async with self._connection_locks[codec]:
                await self._ensure_connection(codec)
        except Exception:
            pass

    async def _reset_connection(self, codec: str) -> None:
        context = self._connection_contexts.pop(codec, None)
        self._websockets.pop(codec, None)
        self._last_used.pop(codec, None)
        if context is not None:
            try:
                await asyncio.wait_for(context.__aexit__(None, None, None), timeout=3)
            except (Exception, asyncio.CancelledError):
                pass

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self._stream_with_codec(text, "mp3"):
            yield chunk

    async def stream_realtime(self, text: str) -> AsyncIterator[bytes]:
        """Stream linear16 PCM for low-latency Web Audio playback in the browser."""
        async for chunk in self._stream_with_codec(text, "linear16"):
            yield chunk

    async def _stream_with_codec(self, text: str, codec: str) -> AsyncIterator[bytes]:
        if not text.strip():
            raise ValueError("Cannot synthesize empty text")
        async with self._connection_locks[codec]:
            for attempt in range(2):
                await self._ensure_connection(codec)
                websocket = self._websockets[codec]
                received_audio = False
                try:
                    await asyncio.wait_for(websocket.convert(text), timeout=self.operation_timeout_seconds)
                    await asyncio.wait_for(websocket.flush(), timeout=self.operation_timeout_seconds)
                    while True:
                        message = await asyncio.wait_for(
                            websocket.recv(), timeout=self.operation_timeout_seconds,
                        )
                        message_type = getattr(message, "type", None)
                        if message_type == "audio":
                            encoded = getattr(getattr(message, "data", None), "audio", None)
                            if not encoded:
                                continue
                            chunk = base64.b64decode(encoded, validate=True)
                            if chunk:
                                received_audio = True
                                self._last_used[codec] = time.monotonic()
                                yield chunk
                        elif message_type == "error":
                            raise RuntimeError("Sarvam TTS returned a stream error")
                        elif message_type == "event":
                            event_type = getattr(getattr(message, "data", None), "event_type", None)
                            if event_type == "final":
                                break
                    if not received_audio:
                        raise ValueError("Sarvam TTS returned an empty stream")
                    self._last_used[codec] = time.monotonic()
                    return
                except asyncio.CancelledError:
                    await asyncio.shield(self._reset_connection(codec))
                    raise
                except ValueError:
                    await self._reset_connection(codec)
                    raise
                except BaseException as error:
                    await self._reset_connection(codec)
                    if attempt == 0 and not received_audio:
                        continue
                    raise

    async def synthesize(self, text: str) -> bytes:
        """Collect streamed chunks for callers that still require a complete response."""
        chunks = [chunk async for chunk in self.stream(text)]
        if not chunks:
            raise ValueError("Sarvam TTS returned an empty stream")
        return b"".join(chunks)

    async def close(self) -> None:
        for codec, lock in self._connection_locks.items():
            async with lock:
                await self._reset_connection(codec)
        close_client = getattr(self._client, "close", None) or getattr(self._client, "aclose", None)
        if close_client is not None:
            result = close_client()
            if hasattr(result, "__await__"):
                await result
