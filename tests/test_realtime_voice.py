import asyncio
import json
from types import SimpleNamespace

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.providers.schemas import IntentProposal
from kural.voice.orchestrator import RealtimeVoiceOrchestrator, is_spurious_hallucination


class FakeLLM:
    provider_name = "fake"
    model_name = "realtime-test"

    def __init__(self):
        self.calls = []

    def classify(self, text):
        self.calls.append(text)
        return IntentProposal(intent=Intent.OTHER, confidence=0.99)


class FakeSTTSession:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []

    async def send_audio(self, pcm16_mono):
        self.sent.append(pcm16_mono)
        if len(self.sent) == 1:
            for event in (
                SimpleNamespace(event="vad.speech_start"),
                SimpleNamespace(event="transcript.partial", text="I'm busy right now"),
                SimpleNamespace(event="transcript.final", text="I'm busy right now, call me later"),
            ):
                await self.events.put(event)

    async def receive_event(self):
        return await self.events.get()


class FakeRealtimeTTS:
    realtime_sample_rate = 24000

    def __init__(self):
        self.calls = []

    async def stream_realtime(self, text):
        self.calls.append(text)
        yield b"\x01\x00" * 16


class FakeWebSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.connected = asyncio.Event()
        self.callback_response_done = asyncio.Event()
        self._assistant_turn_count = 0

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, payload):
        self.sent.append(payload)
        if payload.get("type") == "connected":
            self.connected.set()
        if payload.get("type") == "assistant_message" and payload.get("turn"):
            self._assistant_turn_count += 1
        if payload.get("type") == "assistant_done" and payload.get("turn"):
            self.callback_response_done.set()

    async def send_bytes(self, payload):
        self.sent.append(payload)


def test_realtime_pcm_reaches_kural_and_identity_busy_creates_callback(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    llm, stt, tts, websocket = FakeLLM(), FakeSTTSession(), FakeRealtimeTTS(), FakeWebSocket()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, tts, llm)

    async def scenario():
        task = asyncio.create_task(orchestrator.run(conversation.session_id))
        await asyncio.wait_for(websocket.connected.wait(), timeout=1)
        await websocket.incoming.put({"type": "websocket.receive", "bytes": b"\x00\x00" * 320})
        await asyncio.wait_for(websocket.callback_response_done.wait(), timeout=2)
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())

    session = repository.get_session(conversation.session_id)
    assert stt.sent == [b"\x00\x00" * 320]
    assert session.state == State.ENDED
    assert repository.list_callbacks(conversation.session_id)
    assert not llm.calls  # identity deferral is handled deterministically before Gemini
    assert any(isinstance(item, bytes) for item in websocket.sent)
    assert any(item.get("type") == "transcript_partial" for item in websocket.sent if isinstance(item, dict))
    assert any(item.get("type") == "call_ended" for item in websocket.sent if isinstance(item, dict))


def test_realtime_client_end_closes_without_waiting_for_another_turn(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    websocket, stt = FakeWebSocket(), FakeSTTSession()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, FakeRealtimeTTS(), FakeLLM())

    async def scenario():
        task = asyncio.create_task(orchestrator.run(conversation.session_id))
        await asyncio.wait_for(websocket.connected.wait(), timeout=1)
        await websocket.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "end"})})
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert repository.get_session(conversation.session_id).state == State.IDENTITY_CHECK


def test_realtime_user_text_triggers_kural_turn_and_speaks(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    websocket, stt = FakeWebSocket(), FakeSTTSession()
    tts = FakeRealtimeTTS()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, tts, FakeLLM())

    async def scenario():
        task = asyncio.create_task(orchestrator.run(conversation.session_id))
        await asyncio.wait_for(websocket.connected.wait(), timeout=1)
        # Send user text turn
        await websocket.incoming.put({
            "type": "websocket.receive",
            "text": json.dumps({"type": "user_text", "text": "I'm busy right now, call me later"}),
        })
        await asyncio.wait_for(websocket.callback_response_done.wait(), timeout=2)
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    session = repository.get_session(conversation.session_id)
    assert session.state == State.ENDED
    assert repository.list_callbacks(conversation.session_id)
    assert any(
        isinstance(item, dict) and item.get("type") == "assistant_message" and item.get("turn") == 1
        for item in websocket.sent
    )
    final_message = next(
        item for item in websocket.sent
        if isinstance(item, dict) and item.get("type") == "assistant_message" and item.get("turn") == 1
    )
    assert "do not share your OTP or password with anyone" in final_message["text"]
    assert any(isinstance(item, bytes) for item in websocket.sent)


def test_realtime_user_sensitive_data_blocks_and_speaks_safety_response(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    websocket, stt = FakeWebSocket(), FakeSTTSession()
    tts = FakeRealtimeTTS()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, tts, FakeLLM())

    async def scenario():
        task = asyncio.create_task(orchestrator.run(conversation.session_id))
        await asyncio.wait_for(websocket.connected.wait(), timeout=1)
        await websocket.incoming.put({
            "type": "websocket.receive",
            "text": json.dumps({"type": "user_text", "text": "My OTP is 123456"}),
        })
        await asyncio.wait_for(websocket.callback_response_done.wait(), timeout=2)
        # User ends call explicitly since sensitive data does not end the call
        await websocket.incoming.put({
            "type": "websocket.receive",
            "text": json.dumps({"type": "end"}),
        })
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    session = repository.get_session(conversation.session_id)
    assert not repository.list_callbacks(conversation.session_id)
    messages = [item for item in websocket.sent if isinstance(item, dict) and item.get("type") == "assistant_message" and item.get("turn") == 1]
    assert len(messages) == 1
    assert messages[0]["policy_decision"] == "BLOCKED"
    assert "Please don't share your OTP" in messages[0]["text"]
    assert "123456" not in str(repository.get_session_detail(conversation.session_id))
    assert any(isinstance(item, bytes) for item in websocket.sent)


def test_partial_hypotheses_do_not_become_customer_turns(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    websocket, stt = FakeWebSocket(), FakeSTTSession()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, FakeRealtimeTTS(), FakeLLM())
    orchestrator._session_id = conversation.session_id

    async def scenario():
        for event in (
            SimpleNamespace(event="vad.speech_start"),
            SimpleNamespace(event="transcript.partial", text="However, even if you want to learn"),
            SimpleNamespace(event="vad.speech_end"),
            SimpleNamespace(event="error", code="TEST_EXIT", is_fatal=True),
        ):
            await stt.events.put(event)
        await orchestrator._read_sarvam(0.0)

    asyncio.run(scenario())
    assert repository.get_session(conversation.session_id).turn_order == 0
    assert is_spurious_hallucination("however, even if you want to learn learn")
    assert any(
        item.get("type") == "transcript_partial" and item.get("preview_suppressed")
        for item in websocket.sent if isinstance(item, dict)
    )


def test_assistant_playback_echo_is_suppressed_before_partial_reaches_browser(repository):
    engine = KuralEngine(repository)
    conversation, _ = engine.create_session()
    websocket, stt = FakeWebSocket(), FakeSTTSession()
    orchestrator = RealtimeVoiceOrchestrator(websocket, repository, stt, FakeRealtimeTTS(), FakeLLM())
    orchestrator._session_id = conversation.session_id
    spoken_text = "So, another question. Yes. Yes. Yes. Yes."
    orchestrator._recent_assistant_utterances.append(spoken_text)
    orchestrator._is_assistant_speaking = True

    async def scenario():
        for event in (
            SimpleNamespace(event="transcript.partial", text="So, another question. Yes."),
            SimpleNamespace(event="transcript.final", text=spoken_text),
            SimpleNamespace(event="error", code="TEST_EXIT", is_fatal=True),
        ):
            await stt.events.put(event)
        await orchestrator._read_sarvam(0.0)

    asyncio.run(scenario())

    partials = [
        item for item in websocket.sent
        if isinstance(item, dict) and item.get("type") == "transcript_partial"
    ]
    assert partials == [{"type": "transcript_partial", "text": "", "preview_suppressed": True}]
    assert repository.get_session(conversation.session_id).turn_order == 0


def test_credential_disclosure_without_a_code_warns_without_ending_call(repository):
    engine = KuralEngine(repository, llm_provider=FakeLLM())
    conversation, _ = engine.create_session()
    engine.turn(conversation.session_id, "yes")
    engine.begin_live_call(conversation.session_id)

    result = engine.turn(conversation.session_id, "My OTP is")

    assert result.state == State.IDENTITY_CHECK
    assert not result.ended
    assert result.policy_decision == "BLOCKED"
    assert "Please don't share your OTP" in result.response
    assert "That's okay, we can carry on." in result.response


def test_automatic_silence_closing_includes_security_reminder(repository):
    orchestrator = RealtimeVoiceOrchestrator(
        FakeWebSocket(), repository, FakeSTTSession(), FakeRealtimeTTS(), FakeLLM()
    )

    closing = orchestrator._get_silence_closing_text()

    assert "do not share your OTP or password with anyone" in closing
