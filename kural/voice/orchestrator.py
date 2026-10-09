"""Transport orchestration for a continuous browser voice call.

This module coordinates provider-neutral STT/TTS interfaces with KURAL.
Equipped with:
1. Acoustic Echo Cancellation & Self-Speech Filtering
2. Noise, Filler & Hallucination Suppression
3. Turn Deduplication and Turn Serialization Locking
4. Client Playback Gating & Low-Latency User Barge-in
5. Precision Turn Telemetry (T0 -> T8) & Metrics Registry Integration
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from kural.conversation.engine import KuralEngine
from kural.privacy.transcript import safe_transcript
from kural.repositories import KuralRepository
from kural.providers.contracts import LLMProvider, RealtimeSTTSession, TTSProvider
from kural.telemetry.metrics import metrics_registry

logger = logging.getLogger(__name__)
MAX_PCM_MESSAGE_BYTES = 16_000  # 500 ms at 16 kHz mono LINEAR16; browser normally sends 20 ms.

DISCARD_NOISE_TOKENS = {
    "", "huh", "um", "uh", "ah", "mm", "hmm", "mhm", "eh", "oh",
    ".", "..", "...", "?", "!",
    "you", "the", "a", "an", "so", "and", "or",
    "subbu", "town bank",
}

LEGITIMATE_SHORT_REPLIES = {
    "yes", "no", "ok", "okay", "yep", "nope", "hi", "hey",
    "stop", "sure", "fine", "correct", "myself", "speaking",
}


def normalize_text_words(text: str) -> list[str]:
    """Strip punctuation and lowercase into word tokens."""
    return re.findall(r"\b[a-zA-Z0-9']+\b", text.lower())


def is_acoustic_echo(transcript: str, assistant_utterances: list[str]) -> bool:
    """Detect if an incoming transcript is self-speech acoustic feedback from device speakers."""
    t_words = normalize_text_words(transcript)
    if not t_words:
        return True

    # If transcript starts with an explicit affirmative or negative token, it's user input
    if t_words[0] in {"yes", "no", "yep", "nope", "yeah", "sure", "correct", "myself", "stop"}:
        return False
    if " ".join(t_words) in LEGITIMATE_SHORT_REPLIES:
        return False

    t_str = " ".join(t_words)

    for utterance in assistant_utterances:
        u_words = normalize_text_words(utterance)
        if not u_words:
            continue
        u_str = " ".join(u_words)

        # 1. Exact phrase substring match (e.g. "am i speaking with rahul")
        if t_str in u_str:
            return True

        # 2. Token overlap: if >= 50% of transcript words appear in assistant prompt
        if len(t_words) >= 2:
            matching_words = sum(1 for w in t_words if w in u_words)
            if matching_words / len(t_words) >= 0.50:
                return True

    return False


class RealtimeVoiceOrchestrator:
    def __init__(self, websocket: WebSocket, repository: KuralRepository,
                 stt: RealtimeSTTSession, tts: TTSProvider,
                 llm_provider: LLMProvider) -> None:
        self.websocket = websocket
        self.repository = repository
        self.stt = stt
        self.tts = tts
        self.llm_provider = llm_provider
        self.engine = KuralEngine(repository, llm_provider=llm_provider)
        self._send_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._tts_task: asyncio.Task[None] | None = None
        self._turn_sequence = 0
        self._first_pcm_at: float | None = None
        self._speech_started_at: float | None = None
        self._closed = asyncio.Event()
        self._session_id = ""
        self._is_opening_greeting = False
        self._is_assistant_speaking = False
        self._is_client_playing = False
        self._last_assistant_speech_ended_at = 0.0
        self._recent_assistant_utterances: list[str] = []
        self._last_processed_transcript = ""
        self._last_processed_at = 0.0
        self._pcm_buffer: bytearray = bytearray()
        self._mic_frames_received = 0

    async def _send_json(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def _send_audio(self, chunk: bytes) -> None:
        async with self._send_lock:
            await self.websocket.send_bytes(chunk)

    async def _timing(self, name: str, started_at: float, *, log: bool = False) -> None:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        await self._send_json({"type": "timing", "name": name, "elapsed_ms": elapsed_ms})
        if log:
            logger.info(
                "Voice timing session=%s stage=%s elapsed_ms=%.1f",
                self._session_id, name, elapsed_ms,
            )

    async def run(self, session_id: str, *, resume: bool = False) -> None:
        if self.repository.get_session(session_id) is None:
            await self._send_json({"type": "voice_error", "detail": "This call session is no longer available."})
            return
        self._session_id = session_id
        metrics_registry.active_voice_sessions.inc(1.0)
        try:
            if not resume:
                self.engine.begin_live_call(session_id)
            call_started = time.perf_counter()

            if resume:
                prewarm = getattr(self.tts, "prewarm", None)
                if callable(prewarm):
                    asyncio.create_task(prewarm())

            await self._send_json({"type": "connected", "session_id": session_id})
            if not resume:
                opening = KuralEngine.opening_message()
                self._recent_assistant_utterances.append(opening)
                self._is_assistant_speaking = True
                await self._send_json({
                    "type": "assistant_message", "text": opening,
                    "state": "IDENTITY_CHECK", "intent": None, "policy_decision": "ALLOWED",
                    "ended": False, "opening": True,
                })
                self._tts_task = asyncio.create_task(self._start_speech(opening, call_started, ended=False, is_opening=True))

            reader = asyncio.create_task(self._read_microphone(call_started))
            receiver = asyncio.create_task(self._read_sarvam(call_started))
            closed_waiter = asyncio.create_task(self._closed.wait())
            try:
                done, pending = await asyncio.wait(
                    {reader, receiver, closed_waiter}, return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    error = task.exception() if not task.cancelled() else None
                    if error and not isinstance(error, WebSocketDisconnect):
                        raise error
            finally:
                self._closed.set()
                if self._pcm_buffer:
                    try:
                        from kural.services.recording_service import save_pcm_to_wav
                        save_pcm_to_wav(self._session_id, bytes(self._pcm_buffer))
                    except Exception as exc:
                        logger.debug("Failed to persist call WAV recording for session %s: %s", self._session_id, exc)
                try:
                    db = getattr(self.repository, "database", None)
                    if db is not None:
                        from sqlalchemy import select
                        from kural.persistence.models import CallRecordRow
                        with db.session() as s:
                            cr = s.scalar(select(CallRecordRow).where(CallRecordRow.session_id == self._session_id))
                            if cr:
                                cr.duration_sec = int(time.perf_counter() - call_started)
                                cr.recording_available = True
                                cr.status = "COMPLETED"
                                s.commit()
                except Exception as exc:
                    logger.warning("Failed to finalize call record duration for session %s: %s", self._session_id, exc)
        finally:
            metrics_registry.active_voice_sessions.dec(1.0)

    async def _read_microphone(self, call_started: float) -> None:
        while not self._closed.is_set():
            message = await self.websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            pcm = message.get("bytes")
            if pcm is not None:
                if not pcm or len(pcm) > MAX_PCM_MESSAGE_BYTES or len(pcm) % 2:
                    await self._send_json({"type": "voice_error", "detail": "Invalid microphone audio frame."})
                    continue
                self._pcm_buffer.extend(pcm)
                self._mic_frames_received += 1
                if self._first_pcm_at is None:
                    self._first_pcm_at = time.perf_counter()
                    await self._timing("mic_audio_start", call_started, log=True)
                if self._mic_frames_received % 100 == 0:
                    await self._send_json({
                        "type": "audio_diagnostics",
                        "mic_frames": self._mic_frames_received,
                        "bytes": len(self._pcm_buffer),
                    })
                await self.stt.send_audio(pcm)
                continue
            text = message.get("text")
            if text:
                try:
                    control = json.loads(text)
                except Exception:
                    continue
                kind = control.get("type") if isinstance(control, dict) else None
                if kind == "end":
                    self._closed.set()
                    end = getattr(self.stt, "end", None)
                    if callable(end):
                        await end()
                    return
                if kind == "playback_status":
                    status = control.get("status")
                    if status == "playing":
                        self._is_client_playing = True
                    elif status == "idle":
                        self._is_client_playing = False
                        self._last_assistant_speech_ended_at = time.perf_counter()
                    continue
                if kind == "retry_speech":
                    last_utt = self._recent_assistant_utterances[-1] if self._recent_assistant_utterances else KuralEngine.opening_message()
                    if self._tts_task is not None and not self._tts_task.done():
                        self._tts_task.cancel()
                        await asyncio.gather(self._tts_task, return_exceptions=True)
                    self._tts_task = asyncio.create_task(
                        self._start_speech(last_utt, call_started, ended=False, is_opening=True)
                    )
                    continue
                if kind == "user_text":
                    user_utterance = str(control.get("text", "")).strip()
                    if user_utterance:
                        if self._tts_task is not None and not self._tts_task.done():
                            self._tts_task.cancel()
                            await asyncio.gather(self._tts_task, return_exceptions=True)
                            self._tts_task = None
                            await self._send_json({"type": "barge_in"})
                        self._is_assistant_speaking = False
                        self._is_client_playing = False
                        await self._final_transcript(user_utterance, call_started)
                    continue
                if kind == "client_timing" and control.get("name") in {
                    "mic_capture_started", "browser_playback_started", "call_ended",
                }:
                    logger.info(
                        "Voice client timing session=%s stage=%s elapsed_ms=%s",
                        self._session_id, control["name"], control.get("elapsed_ms"),
                    )

    async def _read_sarvam(self, call_started: float) -> None:
        while not self._closed.is_set():
            event = await self.stt.receive_event()
            event_name = getattr(event, "event", None)
            if event_name == "vad.speech_start":
                self._speech_started_at = time.perf_counter()
                # If assistant is currently speaking, do not cancel speech on VAD start alone;
                # speaker feedback frequently triggers VAD. Wait for transcript confirmation.
                if not (self._is_assistant_speaking or self._is_client_playing):
                    await self._send_json({"type": "speech_started"})
            elif event_name == "transcript.partial":
                if self._speech_started_at is not None:
                    await self._timing("first_stt_partial", self._speech_started_at, log=True)
                partial_text = getattr(event, "text", "")
                if partial_text:
                    await self._send_json({
                        "type": "transcript_partial", "text": safe_transcript(partial_text),
                    })
            elif event_name == "transcript.final":
                transcript = getattr(event, "text", "").strip()
                if not transcript:
                    continue
                clean = transcript.strip(" .,!?;:-_")
                clean_lower = clean.lower()

                # 1. Reject noise, fillers, single-character hallucinations
                if clean_lower in DISCARD_NOISE_TOKENS:
                    logger.info("Discarding noise/filler token session=%s: %s", self._session_id, transcript)
                    continue
                if len(clean) < 2 and clean_lower not in LEGITIMATE_SHORT_REPLIES:
                    logger.info("Discarding low-energy/noise STT transcript session=%s: %s", self._session_id, transcript)
                    continue
                if len(clean.split()) == 1 and len(clean) < 3 and clean_lower not in LEGITIMATE_SHORT_REPLIES:
                    logger.info("Discarding single-char non-reply token session=%s: %s", self._session_id, transcript)
                    continue

                # 2. Acoustic echo / self-speech suppression
                is_currently_speaking = (
                    self._is_assistant_speaking
                    or self._is_client_playing
                    or (time.perf_counter() - self._last_assistant_speech_ended_at < 1.2)
                )

                if is_acoustic_echo(clean, self._recent_assistant_utterances):
                    logger.info(
                        "Discarding acoustic echo self-transcription session=%s (is_speaking=%s): %s",
                        self._session_id, is_currently_speaking, transcript,
                    )
                    continue

                # 3. User barge-in during assistant speech
                if is_currently_speaking:
                    logger.info("User barge-in detected session=%s: %s", self._session_id, transcript)
                    if self._tts_task is not None and not self._tts_task.done():
                        self._tts_task.cancel()
                        await asyncio.gather(self._tts_task, return_exceptions=True)
                        self._tts_task = None
                    await self._send_json({"type": "barge_in"})
                    self._is_assistant_speaking = False
                    self._is_client_playing = False

                # 4. Process valid customer turn exactly once
                await self._final_transcript(clean, call_started)
            elif event_name == "error":
                logger.warning(
                    "Realtime STT error session=%s code=%s fatal=%s",
                    self._session_id, getattr(event, "code", "unknown"), getattr(event, "is_fatal", False),
                )
                await self._send_json({
                    "type": "voice_error",
                    "detail": "Speech recognition connection failed. End this call and try again.",
                    "fatal": bool(getattr(event, "is_fatal", False)),
                })
                if getattr(event, "is_fatal", False):
                    self._closed.set()
                    return
            elif event_name == "session.begin":
                request_id = getattr(event, "request_id", None)
                logger.info("Realtime STT connected session=%s request_id=%s", self._session_id, request_id)

    async def _final_transcript(self, transcript: str, call_started: float) -> None:
        async with self._turn_lock:
            clean = transcript.strip(" .,!?;:-_")
            if not clean:
                return

            now = time.perf_counter()
            # Deduplication: suppress identical transcript arriving within 2.5 seconds
            if clean.lower() == self._last_processed_transcript.lower() and (now - self._last_processed_at) < 2.5:
                logger.info("Discarding duplicate final transcript session=%s: %s", self._session_id, transcript)
                return

            self._last_processed_transcript = clean
            self._last_processed_at = now

            if self._tts_task is not None and not self._tts_task.done():
                self._tts_task.cancel()
                await asyncio.gather(self._tts_task, return_exceptions=True)
                self._tts_task = None

            self._turn_sequence += 1
            turn_id = self._turn_sequence
            final_at = time.perf_counter()
            turn_started = final_at
            speech_started = self._speech_started_at or final_at
            await self._timing("final_stt", speech_started, log=True)
            await self._send_json({"type": "transcript_final", "text": safe_transcript(clean), "turn": turn_id})
            provider_stages: list[tuple[str, float]] = []

            def capture_stage(name: str) -> None:
                provider_stages.append((name, time.perf_counter()))

            turn_result = await run_in_threadpool(
                self.engine.turn,
                self._session_id,
                clean,
                on_timing=capture_stage,
            )
            t5_kural_done = time.perf_counter()
            t3_llm_start = next((t for name, t in provider_stages if name == "llm_request_start"), turn_started)
            t4_llm_response = next((t for name, t in provider_stages if name == "llm_response_start"), t5_kural_done)

            for name, occurred_at in provider_stages:
                await self._send_json({
                    "type": "timing", "name": name,
                    "elapsed_ms": round((occurred_at - turn_started) * 1000, 1),
                })
            await self._send_json({
                "type": "assistant_message", "text": turn_result.response,
                "state": turn_result.state.value, "intent": turn_result.intent.value,
                "policy_decision": turn_result.policy_decision,
                "callback_id": turn_result.callback_id, "case_id": turn_result.case_id,
                "secondary_question": turn_result.secondary_question,
                "fallback_used": turn_result.fallback_used,
                "ended": turn_result.ended, "turn": turn_id,
            })
            logger.info(
                "Voice KURAL turn session=%s state=%s intent=%s processing_ms=%.1f fallback=%s",
                self._session_id, turn_result.state.value, turn_result.intent.value,
                (time.perf_counter() - turn_started) * 1000, turn_result.fallback_used,
            )

            # Record assistant response in recent utterances for echo filtering
            self._recent_assistant_utterances.append(turn_result.response)
            if len(self._recent_assistant_utterances) > 6:
                self._recent_assistant_utterances.pop(0)

            turn_telemetry_ctx = {
                "turn_id": turn_id,
                "speech_started": speech_started,
                "stt_final_at": final_at,
                "t3_llm_start": t3_llm_start,
                "t4_llm_response": t4_llm_response,
                "t5_kural_done": t5_kural_done,
                "turn_result": turn_result,
            }
            self._tts_task = asyncio.create_task(
                self._start_speech(
                    turn_result.response, turn_started, ended=turn_result.ended,
                    turn_id=turn_id, turn_telemetry_ctx=turn_telemetry_ctx,
                ),
            )

    async def _start_speech(self, text: str, call_started: float, *, ended: bool,
                            turn_id: int | None = None, is_opening: bool = False,
                            turn_telemetry_ctx: dict[str, Any] | None = None) -> None:
        self._is_assistant_speaking = True
        if is_opening:
            self._is_opening_greeting = True
        try:
            await self._send_json({"type": "tts_started", "turn": turn_id})
            tts_started = time.perf_counter()
            await self._timing("tts_request_start", call_started, log=True)
            stream = getattr(self.tts, "stream_realtime", None)
            if not callable(stream):
                await self._send_json({"type": "tts_error", "detail": "Realtime speech output is unavailable; the text response is shown."})
                await self._send_json({"type": "assistant_done", "ended": ended, "turn": turn_id})
                return
            first_chunk = True
            try:
                async for chunk in stream(text):
                    if first_chunk:
                        first_chunk = False
                        t7_first_chunk = time.perf_counter()
                        elapsed_first_audio_ms = (t7_first_chunk - call_started) * 1000.0
                        metrics_registry.turn_latency_first_audio_ms.observe(elapsed_first_audio_ms)
                        await self._timing("first_tts_audio_chunk", tts_started, log=True)
                        await self._send_json({"type": "audio_format", "encoding": "linear16", "sample_rate": int(getattr(self.tts, "realtime_sample_rate", 24000)), "channels": 1, "turn": turn_id})

                        if turn_telemetry_ctx is not None:
                            sp_start = turn_telemetry_ctx["speech_started"]
                            stt_fin = turn_telemetry_ctx["stt_final_at"]
                            t3 = turn_telemetry_ctx["t3_llm_start"]
                            t4 = turn_telemetry_ctx["t4_llm_response"]
                            t5 = turn_telemetry_ctx["t5_kural_done"]
                            tr = turn_telemetry_ctx["turn_result"]
                            telemetry = {
                                "type": "turn_telemetry",
                                "turn": turn_id,
                                "provider": self.llm_provider.provider_name,
                                "model": self.llm_provider.model_name,
                                "fallback_used": tr.fallback_used,
                                "secondary_question": tr.secondary_question,
                                "timings": {
                                    "t0_customer_speech_end_ms": 0.0,
                                    "t1_vad_endpoint_ms": round((stt_fin - sp_start) * 1000, 1),
                                    "t2_stt_final_ms": round((stt_fin - sp_start) * 1000, 1),
                                    "t3_llm_start_ms": round((t3 - sp_start) * 1000, 1),
                                    "t4_llm_response_ms": round((t4 - sp_start) * 1000, 1),
                                    "t5_kural_decision_ms": round((t5 - sp_start) * 1000, 1),
                                    "t6_tts_start_ms": round((tts_started - sp_start) * 1000, 1),
                                    "t7_first_audio_ms": round((t7_first_chunk - sp_start) * 1000, 1),
                                },
                                "stages": {
                                    "stt_ms": round((stt_fin - sp_start) * 1000, 1),
                                    "llm_ms": round(max(0.0, (t4 - t3) * 1000), 1),
                                    "kural_ms": round(max(0.0, (t5 - t4) * 1000), 1),
                                    "tts_first_chunk_ms": round(max(0.0, (t7_first_chunk - tts_started) * 1000), 1),
                                    "total_turn_response_ms": round(max(0.0, (t7_first_chunk - sp_start) * 1000), 1),
                                },
                            }
                            await self._send_json(telemetry)
                            logger.info(
                                "Turn telemetry turn=%s provider=%s model=%s fallback=%s total_ms=%.1f llm_ms=%.1f tts_ms=%.1f",
                                turn_id, self.llm_provider.provider_name, self.llm_provider.model_name,
                                tr.fallback_used,
                                telemetry["stages"]["total_turn_response_ms"],
                                telemetry["stages"]["llm_ms"],
                                telemetry["stages"]["tts_first_chunk_ms"],
                            )
                    await self._send_audio(bytes(chunk))
                if first_chunk:
                    raise ValueError("empty TTS stream")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Realtime TTS failed session=%s error_type=%s", self._session_id, type(error).__name__)
                await self._send_json({
                    "type": "tts_error",
                    "detail": "Voice playback is unavailable right now. You can retry voice playback or use typed responses.",
                    "recoverable": True,
                })
            await self._timing("final_audio", tts_started, log=True)
            elapsed_full_turn_ms = (time.perf_counter() - call_started) * 1000.0
            metrics_registry.turn_latency_full_ms.observe(elapsed_full_turn_ms)
            await self._send_json({"type": "assistant_done", "ended": ended, "turn": turn_id})
            if ended:
                self._closed.set()
                await self._send_json({"type": "call_ended", "reason": "conversation_completed"})
        finally:
            self._is_assistant_speaking = False
            self._last_assistant_speech_ended_at = time.perf_counter()
            if is_opening:
                self._is_opening_greeting = False
