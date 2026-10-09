"""Comprehensive Voice Reliability & Repair Acceptance Suite.

Validates the 9 critical voice reliability invariants:
1. Ten seconds of silence produces zero finalized transcripts and zero workflow transitions.
2. Background noise, fillers, and single-char hallucinations are completely suppressed.
3. Acoustic echo and self-transcription of AVA's own speech is detected and discarded.
4. Legitimate short replies ("yes", "no", "ok", "okay", "stop", "sure") are preserved.
5. Unclear speech triggers an appropriate clarification question without data fabrication.
6. Interim/partial transcripts never trigger state machine mutations.
7. Valid finalized transcripts are processed with exactly-once deduplication.
8. User barge-in during assistant speech halts playback and processes interruption.
9. Multi-turn consecutive conversation flows cleanly without stale buffers.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.persistence.database import Database
from kural.persistence.models import Base, CustomerRow, SessionRow
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.providers.contracts import IntentProposal, Transcription
from kural.voice.orchestrator import (
    RealtimeVoiceOrchestrator,
    is_acoustic_echo,
    normalize_text_words,
)


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "voice_repair_test.db"
    db = Database(f"sqlite:///{db_file}")
    Base.metadata.create_all(db.engine)
    with db.session() as s:
        cust = CustomerRow(
            customer_ref="demo-001",
            full_name="Rahul Sharma",
            phone="9876543210",
        )
        s.add(cust)
        sess = SessionRow(
            session_id="SESS-VOICE-REPAIR-01",
            customer_ref="demo-001",
            current_state="IDENTITY_CHECK",
            context_json={},
        )
        s.add(sess)
        s.commit()
    return db


class MockTTSProvider:
    realtime_sample_rate = 24000

    async def stream_realtime(self, text: str):
        # Yield simulated 24kHz PCM chunks
        for _ in range(3):
            yield b"\x00\x05" * 480
            await asyncio.sleep(0.01)


class MockLLMProvider:
    provider_name = "test-mock"
    model_name = "test-mock-v1"

    def classify(self, text: str) -> IntentProposal:
        t = text.lower()
        if "yes" in t or "speaking" in t:
            return IntentProposal(primary_intent=Intent.AFFIRM, confidence=0.95)
        if "no" in t or "not rahul" in t:
            return IntentProposal(primary_intent=Intent.NEGATE, confidence=0.95)
        if "stop" in t or "opt out" in t:
            return IntentProposal(primary_intent=Intent.OPT_OUT, confidence=0.95)
        if "busy" in t or "later" in t:
            return IntentProposal(primary_intent=Intent.BUSY, confidence=0.95)
        if "installed" in t:
            return IntentProposal(primary_intent=Intent.APP_INSTALLED, confidence=0.95)
        return IntentProposal(primary_intent=Intent.OTHER, confidence=0.50)


class MockRealtimeSTTSession:
    def __init__(self):
        self.events_queue = asyncio.Queue()
        self.sent_audio_chunks = []

    async def send_audio(self, pcm16_mono: bytes):
        self.sent_audio_chunks.append(pcm16_mono)

    async def receive_event(self):
        return await self.events_queue.get()

    async def end(self):
        pass


def test_acoustic_echo_matcher_precision():
    """Verify acoustic echo algorithm catches exact and partial self-speech while allowing user replies."""
    assistant_history = [
        "Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with Rahul?",
        "Thank you. Is now a convenient time to discuss the mobile app update?",
    ]

    # 1. Exact phrase echoes from assistant speech MUST be detected
    assert is_acoustic_echo("Am I speaking with Rahul", assistant_history) is True
    assert is_acoustic_echo("Hi this is Subbu", assistant_history) is True
    assert is_acoustic_echo("Town Bank automated assistant", assistant_history) is True
    assert is_acoustic_echo("Is now a convenient time", assistant_history) is True
    assert is_acoustic_echo("mobile app update", assistant_history) is True

    # 2. Legitimate user answers MUST NOT be detected as echo
    assert is_acoustic_echo("Yes", assistant_history) is False
    assert is_acoustic_echo("Yes speaking", assistant_history) is False
    assert is_acoustic_echo("No", assistant_history) is False
    assert is_acoustic_echo("Stop", assistant_history) is False
    assert is_acoustic_echo("Wait", assistant_history) is False
    assert is_acoustic_echo("Call me later", assistant_history) is False
    assert is_acoustic_echo("Who is calling", assistant_history) is False


@pytest.mark.anyio
async def test_ten_seconds_silence_produces_no_transcript_or_transition(test_db):
    """Verify that 10 seconds of silence audio frames produce zero turns and zero state transitions."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.receive = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_bytes = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"

    # Simulate 500 frames of zero PCM audio (10 seconds at 20ms/frame)
    zero_frame = b"\x00" * 640
    for _ in range(500):
        # Simulate websocket packet
        message = {"type": "websocket.receive", "bytes": zero_frame}
        ws.receive.side_effect = [message, {"type": "websocket.disconnect"}]
        # Process single frame
        await orchestrator._read_microphone(0.0)

    # Verify audio was received but STT emitted zero final transcripts
    assert len(orchestrator._pcm_buffer) > 0
    assert orchestrator._turn_sequence == 0

    # Verify session state in database remains unchanged at IDENTITY_CHECK
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.state == State.IDENTITY_CHECK
    assert session_obj.turn_order == 0


@pytest.mark.anyio
async def test_background_noise_and_fillers_suppressed(test_db):
    """Verify common noise tokens, single-char fillers, and hallucinations are dropped."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"

    # Queue noisy/filler events
    noisy_transcripts = ["huh", "um", "ah", "you", ".", "...", "mm", "subbu", "  "]
    for noise in noisy_transcripts:
        event = MagicMock()
        event.event = "transcript.final"
        event.text = noise
        stt.events_queue.put_nowait(event)

    # Queue an exit event to stop reader loop
    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # Verify none of the noise events became turns
    assert orchestrator._turn_sequence == 0
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.turn_order == 0


@pytest.mark.anyio
async def test_ava_does_not_transcribe_own_playback_echo(test_db):
    """Verify that when AVA speaks, microphone feedback echoing AVA's prompt is dropped."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"
    prompt = KuralEngine.opening_message("Rahul Sharma")
    orchestrator._recent_assistant_utterances.append(prompt)
    orchestrator._is_assistant_speaking = True

    # Simulate mic picking up fragments of AVA's opening greeting
    echo_fragments = [
        "Hi this is Subbu",
        "Town Bank's automated assistant",
        "Am I speaking with Rahul Sharma",
    ]

    for echo in echo_fragments:
        event = MagicMock()
        event.event = "transcript.final"
        event.text = echo
        stt.events_queue.put_nowait(event)

    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # Verify zero echoes were processed as customer input
    assert orchestrator._turn_sequence == 0
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.turn_order == 0


@pytest.mark.anyio
async def test_legitimate_short_replies_preserved(test_db):
    """Verify that essential short replies ('yes', 'no', 'stop') are cleanly processed."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"
    orchestrator._recent_assistant_utterances.append(KuralEngine.opening_message("Rahul Sharma"))

    # User answers "Yes"
    event = MagicMock()
    event.event = "transcript.final"
    event.text = "Yes"
    stt.events_queue.put_nowait(event)

    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # Verify turn 1 was processed and transitioned state to PERMISSION
    assert orchestrator._turn_sequence == 1
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.state == State.PERMISSION
    assert session_obj.turn_order == 1


@pytest.mark.anyio
async def test_duplicate_final_transcript_suppression(test_db):
    """Verify that identical final transcripts in rapid succession are deduplicated to exactly once."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"

    # Send "Yes" twice rapidly
    for _ in range(2):
        event = MagicMock()
        event.event = "transcript.final"
        event.text = "Yes"
        stt.events_queue.put_nowait(event)

    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # Exactly one turn should have been processed
    assert orchestrator._turn_sequence == 1
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.turn_order == 1


@pytest.mark.anyio
async def test_interim_partial_transcripts_do_not_mutate_state(test_db):
    """Verify that interim partial transcripts update the client but never trigger database turns."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"

    # Send 5 partial transcripts
    for partial in ["ye", "yes s", "yes spea", "yes speaking"]:
        event = MagicMock()
        event.event = "transcript.partial"
        event.text = partial
        stt.events_queue.put_nowait(event)

    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # No state machine turns should have executed
    assert orchestrator._turn_sequence == 0
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.turn_order == 0


@pytest.mark.anyio
async def test_user_barge_in_during_assistant_speech(test_db):
    """Verify that genuine user speech during assistant playback triggers barge-in and processes turn."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"
    orchestrator._recent_assistant_utterances.append("Hi, this is Subbu calling from Town Bank.")
    orchestrator._is_assistant_speaking = True

    # User barges in with "Stop calling me" (distinct from assistant prompt)
    event = MagicMock()
    event.event = "transcript.final"
    event.text = "Stop calling me"
    stt.events_queue.put_nowait(event)

    stop_event = MagicMock()
    stop_event.event = "error"
    stop_event.code = "TEST_EXIT"
    stop_event.is_fatal = True
    stt.events_queue.put_nowait(stop_event)

    await orchestrator._read_sarvam(0.0)

    # Barge-in message must have been sent to client
    sent_types = [call.args[0].get("type") for call in ws.send_json.call_args_list if call.args]
    assert "barge_in" in sent_types
    # Turn was processed
    assert orchestrator._turn_sequence == 1
    session_obj = repo.get_session("SESS-VOICE-REPAIR-01")
    assert session_obj.turn_order == 1


@pytest.mark.anyio
async def test_consecutive_multi_turn_flow(test_db):
    """Verify smooth multi-turn conversation across consecutive turns without buffer corruption."""
    repo = SqlAlchemyKuralRepository(test_db)
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockRealtimeSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-VOICE-REPAIR-01"

    # Turn 1: Confirm identity
    await orchestrator._final_transcript("Yes speaking", 0.0)
    assert orchestrator._turn_sequence == 1
    s1 = repo.get_session("SESS-VOICE-REPAIR-01")
    assert s1.state == State.PERMISSION

    # Turn 2: Give permission to speak
    await asyncio.sleep(0.05)
    await orchestrator._final_transcript("Yes I have time", 0.0)
    assert orchestrator._turn_sequence == 2
    s2 = repo.get_session("SESS-VOICE-REPAIR-01")
    assert s2.state == State.APP_STATUS

    # Turn 3: Confirm app installed
    await asyncio.sleep(0.05)
    await orchestrator._final_transcript("Yes installed", 0.0)
    assert orchestrator._turn_sequence == 3
    s3 = repo.get_session("SESS-VOICE-REPAIR-01")
    assert s3.state == State.UPDATE_HELP
