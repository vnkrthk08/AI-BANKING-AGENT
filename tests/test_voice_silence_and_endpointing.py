"""Acceptance suite for Speech End Detection, Customer Silence Timeout, and Automatic Call Termination.

Verifies the 12 critical acceptance requirements:
1. Customer says a short sentence ("I have a problem", "Yes", "Stop") and Subbu responds promptly after utterance ends.
2. Customer speaks with natural pauses without having the utterance incorrectly split.
3. Ten to fifteen seconds of actual silence produces no fabricated transcript or fake turns.
4. After opening greeting, customer silence triggers one reminder.
5. Further silence without response triggers closing statement and call termination (NO_RESPONSE).
6. Same reminder and termination behavior works after an ordinary conversational question.
7. Valid customer response arriving just before timeout cancels pending reminder.
8. Background noise, echo and rejected filler tokens do not reset the silence timer indefinitely.
9. STT timeout and network failure are handled as errors, not falsely classified as confirmed customer silence.
10. No duplicate reminders, overlapping closing messages or repeated call-termination events occur.
11. Every timer is cancelled correctly when call ends or new session starts.
12. At least three consecutive call sessions can start and end without page refresh or stale state.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.persistence.database import Database
from kural.persistence.models import Base, CustomerRow, SessionRow, CallRecordRow
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.providers.contracts import IntentProposal
from kural.voice.orchestrator import RealtimeVoiceOrchestrator, is_acoustic_echo


@pytest.fixture
def silence_test_db(tmp_path):
    db_file = tmp_path / "silence_acceptance.db"
    db = Database(f"sqlite:///{db_file}")
    Base.metadata.create_all(db.engine)
    with db.session() as s:
        cust = CustomerRow(
            customer_ref="demo-001",
            full_name="Rahul Sharma",
            phone="9876543210",
            preferred_language="English",
        )
        s.add(cust)
        s.flush()
        sess = SessionRow(
            session_id="SESS-SILENCE-01",
            customer_ref="demo-001",
            current_state="IDENTITY_CHECK",
            context_json={},
        )
        s.add(sess)
        s.flush()
        call = CallRecordRow(
            session_id="SESS-SILENCE-01",
            customer_ref="demo-001",
            status="IN_PROGRESS",
            disposition="IN_PROGRESS",
        )
        s.add(call)
        s.commit()
    return db


class MockTTSProvider:
    realtime_sample_rate = 24000

    def __init__(self):
        self.spoken_texts: list[str] = []

    async def stream_realtime(self, text: str):
        self.spoken_texts.append(text)
        for _ in range(3):
            yield b"\x00\x05" * 480
            await asyncio.sleep(0.005)


class MockLLMProvider:
    provider_name = "test-mock"
    model_name = "test-mock-v1"

    def classify(self, text: str) -> IntentProposal:
        t = text.lower()
        if "yes" in t or "speaking" in t:
            return IntentProposal(primary_intent=Intent.AFFIRM, confidence=0.95)
        if "problem" in t or "issue" in t or "error" in t:
            return IntentProposal(primary_intent=Intent.APP_UPDATE_ISSUE, confidence=0.95)
        if "no" in t or "not rahul" in t:
            return IntentProposal(primary_intent=Intent.NEGATE, confidence=0.95)
        if "stop" in t or "opt out" in t:
            return IntentProposal(primary_intent=Intent.OPT_OUT, confidence=0.95)
        if "busy" in t or "later" in t:
            return IntentProposal(primary_intent=Intent.BUSY, confidence=0.95)
        return IntentProposal(primary_intent=Intent.OTHER, confidence=0.50)


class MockSTTSession:
    def __init__(self):
        self.events_queue = asyncio.Queue()
        self.sent_audio_chunks = []
        self.flush_called = False

    async def send_audio(self, pcm16_mono: bytes):
        self.sent_audio_chunks.append(pcm16_mono)

    async def receive_event(self):
        return await self.events_queue.get()

    async def flush(self):
        self.flush_called = True

    async def end(self):
        pass


class FakeWebSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent_json_messages = []
        self.sent_audio_bytes = []
        self.connected = asyncio.Event()

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, payload):
        self.sent_json_messages.append(payload)
        if payload.get("type") == "connected":
            self.connected.set()

    async def send_bytes(self, payload):
        self.sent_audio_bytes.append(payload)


# ---------------------------------------------------------------------------
# TEST 1: Short sentence responded to promptly; no false echo suppression
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_short_sentence_prompts_immediate_response_after_utterance_ends(silence_test_db):
    """Test 1: Customer says 'I have a problem' and Subbu responds promptly after utterance ends."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    prompt = "Please let me know if the update worked or if you had a problem."
    orchestrator._recent_assistant_utterances.append(prompt)
    orchestrator._session_id = "SESS-SILENCE-01"

    # Verify is_acoustic_echo does NOT discard "I have a problem"
    assert is_acoustic_echo("I have a problem", [prompt], is_currently_speaking=False) is False
    assert is_acoustic_echo("I have a problem", [prompt], is_currently_speaking=True) is False

    # Simulate STT event flow: partial -> final
    t_speech_end = time.perf_counter()
    stt_event = MagicMock()
    stt_event.event = "transcript.final"
    stt_event.text = "I have a problem"
    stt.events_queue.put_nowait(stt_event)

    # Queue fatal error to exit loop
    exit_ev = MagicMock()
    exit_ev.event = "error"
    exit_ev.code = "TEST_EXIT"
    exit_ev.is_fatal = True
    stt.events_queue.put_nowait(exit_ev)

    await orchestrator._read_sarvam(0.0)

    # Measure speech-end to final-transcript latency
    t_processed = time.perf_counter()
    latency_ms = (t_processed - t_speech_end) * 1000.0

    # Verify utterance was processed cleanly
    assert orchestrator._turn_sequence == 1
    assert orchestrator._last_processed_transcript == "I have a problem"
    # Latency should be well under sub-800ms budget (typically <100ms on warm runner)
    assert latency_ms < 300.0

    # Verify assistant response was generated and sent
    msg_types = [m.get("type") for m in ws.sent_json_messages]
    assert "transcript_final" in msg_types
    assert "assistant_message" in msg_types


# ---------------------------------------------------------------------------
# TEST 2: Natural pauses do not split customer utterance
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_natural_pauses_in_speech_do_not_split_utterance(silence_test_db):
    """Test 2: Customer speaks with 300ms pause ('I have... [pause] ...a problem') without premature split."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.turn_silence_window_sec = 0.5  # 500ms window
    orchestrator._session_id = "SESS-SILENCE-01"

    # Part 1 arrives: "I have"
    ev1 = MagicMock()
    ev1.event = "transcript.partial"
    ev1.text = "I have"
    stt.events_queue.put_nowait(ev1)

    # Simulate 250ms pause (less than the 500ms window)
    async def delayed_part2():
        await asyncio.sleep(0.20)
        ev2 = MagicMock()
        ev2.event = "transcript.partial"
        ev2.text = "I have a problem"
        stt.events_queue.put_nowait(ev2)
        # Final arrives shortly after
        await asyncio.sleep(0.10)
        ev3 = MagicMock()
        ev3.event = "transcript.final"
        ev3.text = "I have a problem"
        stt.events_queue.put_nowait(ev3)
        await asyncio.sleep(0.05)
        exit_ev = MagicMock()
        exit_ev.event = "error"
        exit_ev.code = "TEST_EXIT"
        exit_ev.is_fatal = True
        stt.events_queue.put_nowait(exit_ev)

    asyncio.create_task(delayed_part2())
    await orchestrator._read_sarvam(0.0)

    # Exactly 1 turn should have been processed for the whole sentence
    assert orchestrator._turn_sequence == 1
    assert orchestrator._last_processed_transcript == "I have a problem"


# ---------------------------------------------------------------------------
# TEST 3: 10-15 seconds of silence produces zero fabricated transcripts
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_ten_to_fifteen_seconds_of_silence_produces_no_fabricated_transcript(silence_test_db):
    """Test 3: 12 seconds of pure silence produces no customer transcripts and no fake turns."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = AsyncMock()
    ws.receive = AsyncMock()
    ws.send_json = AsyncMock()

    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator._session_id = "SESS-SILENCE-01"

    # 600 frames of zero PCM (12 seconds)
    zero_frame = b"\x00" * 640
    for _ in range(600):
        message = {"type": "websocket.receive", "bytes": zero_frame}
        ws.receive.side_effect = [message, {"type": "websocket.disconnect"}]
        await orchestrator._read_microphone(0.0)

    # Zero turns produced, zero transcript fabrication
    assert orchestrator._turn_sequence == 0
    assert orchestrator._latest_partial_transcript == ""
    assert orchestrator._last_processed_transcript == ""


# ---------------------------------------------------------------------------
# TEST 4: Opening greeting silence triggers exactly one reminder
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_after_opening_greeting_customer_silence_triggers_one_reminder(silence_test_db):
    """Test 4: Customer silence after greeting triggers exactly one reminder."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.15  # Fast timeout for test
    orchestrator._session_id = "SESS-SILENCE-01"

    # Start silence timer
    orchestrator._arm_silence_timer(0.0)
    assert orchestrator._silence_state == "WAITING_INITIAL"

    # Wait for silence timeout to fire
    await asyncio.sleep(0.25)

    # Reminder 1 should have fired
    assert orchestrator._reminder_count == 1
    assert orchestrator._silence_state == "REMINDER_ACTIVE"

    # Verify reminder was sent via JSON and spoken via TTS
    reminder_msg = next((m for m in ws.sent_json_messages if m.get("silence_reminder")), None)
    assert reminder_msg is not None
    assert "still there" in reminder_msg["text"]
    assert any("still there" in text for text in tts.spoken_texts)

    # Clean up
    orchestrator._cancel_silence_timer()


# ---------------------------------------------------------------------------
# TEST 5: Further silence triggers closing statement and NO_RESPONSE termination
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_further_silence_triggers_closing_and_termination(silence_test_db):
    """Test 5: Further silence after reminder triggers closing statement and NO_RESPONSE call termination."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.15
    orchestrator._session_id = "SESS-SILENCE-01"

    # Trigger first timeout (reminder)
    orchestrator._arm_silence_timer(0.0)
    await asyncio.sleep(0.25)
    assert orchestrator._reminder_count == 1

    # Simulate reminder playback finishing -> arm second silence timer
    orchestrator._is_assistant_speaking = False
    orchestrator._is_client_playing = False
    orchestrator._arm_silence_timer(0.0)
    assert orchestrator._silence_state == "WAITING_POST_REMINDER"

    # Wait for second timeout
    await asyncio.sleep(0.25)

    # State must transition to CLOSING
    assert orchestrator._silence_state == "CLOSING"
    closing_msg = next((m for m in ws.sent_json_messages if m.get("silence_closing")), None)
    assert closing_msg is not None
    assert "end the call now" in closing_msg["text"]

    # When TTS completes closing audio, call_ended is emitted with reason no_response
    if orchestrator._tts_task:
        await orchestrator._tts_task
    end_msg = next((m for m in ws.sent_json_messages if m.get("type") == "call_ended"), None)
    assert end_msg is not None
    assert end_msg.get("reason") == "no_response"


# ---------------------------------------------------------------------------
# TEST 6: Silence reminder and termination works after conversational question
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_silence_reminder_and_termination_works_after_conversational_question(silence_test_db):
    """Test 6: Silence behavior applies after an ordinary mid-call conversational turn."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.15
    orchestrator._session_id = "SESS-SILENCE-01"

    # Turn 1: Customer confirms identity
    await orchestrator._final_transcript("Yes speaking", 0.0)
    if orchestrator._tts_task:
        await orchestrator._tts_task

    # Reminder count was reset for the new question
    assert orchestrator._reminder_count == 0

    # Assistant playback completes -> customer is now silent
    orchestrator._is_assistant_speaking = False
    orchestrator._is_client_playing = False
    orchestrator._arm_silence_timer(0.0)

    # Wait for silence timeout
    await asyncio.sleep(0.25)

    # Reminder 1 should have fired
    assert orchestrator._reminder_count == 1
    assert any(m.get("silence_reminder") for m in ws.sent_json_messages)

    orchestrator._cancel_silence_timer()


# ---------------------------------------------------------------------------
# TEST 7: Response arriving just before timeout cancels pending reminder
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_response_just_before_timeout_cancels_pending_reminder(silence_test_db):
    """Test 7: Valid customer response arriving right before timeout cancels pending reminder."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.30
    orchestrator._session_id = "SESS-SILENCE-01"

    # Arm silence timer
    orchestrator._arm_silence_timer(0.0)

    # Wait 150ms (before the 300ms timeout) and send speech
    await asyncio.sleep(0.15)
    ev = MagicMock()
    ev.event = "transcript.final"
    ev.text = "Wait, I am here"
    stt.events_queue.put_nowait(ev)

    exit_ev = MagicMock()
    exit_ev.event = "error"
    exit_ev.code = "TEST_EXIT"
    exit_ev.is_fatal = True
    stt.events_queue.put_nowait(exit_ev)

    await orchestrator._read_sarvam(0.0)

    # User turn was processed
    assert orchestrator._turn_sequence == 1
    # Reminder must NEVER have been emitted
    assert not any(m.get("silence_reminder") for m in ws.sent_json_messages)
    assert orchestrator._reminder_count == 0


# ---------------------------------------------------------------------------
# TEST 8: Noise and echo do not reset silence timer indefinitely
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_noise_and_echo_do_not_reset_silence_timer_indefinitely(silence_test_db):
    """Test 8: Discarded noise tokens ('huh', 'um') and echo do not reset silence timer indefinitely."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.20
    orchestrator._session_id = "SESS-SILENCE-01"
    orchestrator._arm_silence_timer(0.0)

    # Inject filler noise event: "huh"
    noise_ev = MagicMock()
    noise_ev.event = "transcript.final"
    noise_ev.text = "huh"
    stt.events_queue.put_nowait(noise_ev)

    # Let silence timeout expire despite the noise
    async def drain():
        await asyncio.sleep(0.35)
        exit_ev = MagicMock()
        exit_ev.event = "error"
        exit_ev.code = "TEST_EXIT"
        exit_ev.is_fatal = True
        stt.events_queue.put_nowait(exit_ev)

    asyncio.create_task(drain())
    await orchestrator._read_sarvam(0.0)

    # Verify noise was NOT accepted as customer turn
    assert orchestrator._turn_sequence == 0
    # Reminder MUST have fired despite the noise token
    assert orchestrator._reminder_count >= 1

    orchestrator._cancel_silence_timer()


# ---------------------------------------------------------------------------
# TEST 9: STT error handled explicitly, not misclassified as customer silence
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_stt_error_handled_as_explicit_error_not_silence(silence_test_db):
    """Test 9: STT failure surfaces voice_error, never falsely classifying as NO_RESPONSE silence."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 5.0  # Long timeout
    orchestrator._session_id = "SESS-SILENCE-01"
    orchestrator._arm_silence_timer(0.0)

    # Inject fatal STT error
    err_ev = MagicMock()
    err_ev.event = "error"
    err_ev.code = "CONNECTION_LOST"
    err_ev.is_fatal = True
    stt.events_queue.put_nowait(err_ev)

    await orchestrator._read_sarvam(0.0)

    # Verify voice_error was sent
    voice_err_msg = next((m for m in ws.sent_json_messages if m.get("type") == "voice_error"), None)
    assert voice_err_msg is not None
    assert voice_err_msg.get("fatal") is True

    # Silence timer was cancelled, NOT triggered as NO_RESPONSE
    assert orchestrator._silence_state != "CLOSING"
    assert orchestrator._reminder_count == 0


# ---------------------------------------------------------------------------
# TEST 10: No duplicate reminders or overlapping closing messages
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_no_duplicate_reminders_or_overlapping_closing_messages(silence_test_db):
    """Test 10: Exactly one reminder and one closing message occur during full silence lifecycle."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 0.15
    orchestrator._session_id = "SESS-SILENCE-01"

    # Run complete silence timeout lifecycle
    orchestrator._arm_silence_timer(0.0)
    await asyncio.sleep(0.20)  # Reminder 1 fires

    orchestrator._is_assistant_speaking = False
    orchestrator._is_client_playing = False
    orchestrator._arm_silence_timer(0.0)
    await asyncio.sleep(0.20)  # Closing fires

    if orchestrator._tts_task:
        await orchestrator._tts_task

    # Count reminders and closings
    reminders = [m for m in ws.sent_json_messages if m.get("silence_reminder")]
    closings = [m for m in ws.sent_json_messages if m.get("silence_closing")]
    end_events = [m for m in ws.sent_json_messages if m.get("type") == "call_ended"]

    assert len(reminders) == 1
    assert len(closings) == 1
    assert len(end_events) == 1


# ---------------------------------------------------------------------------
# TEST 11: All timers cancelled on call end or new session
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_timers_cancelled_on_call_end_or_new_session(silence_test_db):
    """Test 11: All timer tasks are cleanly cancelled when call concludes."""
    repo = SqlAlchemyKuralRepository(silence_test_db)
    ws = FakeWebSocket()
    stt = MockSTTSession()
    tts = MockTTSProvider()
    llm = MockLLMProvider()

    orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
    orchestrator.silence_timeout_sec = 10.0
    orchestrator._session_id = "SESS-SILENCE-01"

    orchestrator._arm_silence_timer(0.0)
    orchestrator._schedule_turn_finalizer(0.0, debounce_sec=5.0)

    assert orchestrator._silence_timer_task is not None
    assert orchestrator._turn_finalizer_task is not None

    # Cancel explicitly on call end
    orchestrator._cancel_silence_timer()
    orchestrator._cancel_turn_finalizer()

    assert orchestrator._silence_timer_task is None
    assert orchestrator._turn_finalizer_task is None
    assert orchestrator._silence_state == "IDLE"


# ---------------------------------------------------------------------------
# TEST 12: Three consecutive call sessions run without page refresh or stale bleed
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_three_consecutive_call_sessions_without_page_refresh(silence_test_db):
    """Test 12: Three consecutive call sessions start and end cleanly with zero buffer corruption."""
    repo = SqlAlchemyKuralRepository(silence_test_db)

    for i in range(1, 4):
        session_id = f"SESS-CONSECUTIVE-{i:02d}"
        with silence_test_db.session() as s:
            s_row = SessionRow(
                session_id=session_id,
                customer_ref="demo-001",
                current_state="IDENTITY_CHECK",
                context_json={},
            )
            s.add(s_row)
            s.flush()
            c_row = CallRecordRow(
                session_id=session_id,
                customer_ref="demo-001",
                status="IN_PROGRESS",
                disposition="IN_PROGRESS",
            )
            s.add(c_row)
            s.commit()

        ws = FakeWebSocket()
        stt = MockSTTSession()
        tts = MockTTSProvider()
        llm = MockLLMProvider()

        orchestrator = RealtimeVoiceOrchestrator(ws, repo, stt, tts, llm)
        orchestrator._session_id = session_id

        # Each session starts fresh with clean sequence 0
        assert orchestrator._turn_sequence == 0
        assert len(orchestrator._pcm_buffer) == 0

        # Run 1 turn
        await orchestrator._final_transcript("Yes speaking", 0.0)
        assert orchestrator._turn_sequence == 1
        if orchestrator._tts_task:
            await orchestrator._tts_task

        # Conclude session cleanly
        orchestrator._closed.set()
        orchestrator._cancel_silence_timer()
        orchestrator._cancel_turn_finalizer()

        # Database state reflects clean transition
        session_obj = repo.get_session(session_id)
        assert session_obj.state == State.PERMISSION
