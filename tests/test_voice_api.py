from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.providers.contracts import Transcription
from kural.providers.schemas import IntentProposal


class FakeSTT:
    def __init__(self, transcript: str = "My banking app is not updating", *, fail: bool = False) -> None:
        self.transcript = transcript
        self.fail = fail
        self.calls: list[bytes] = []

    def transcribe(self, audio: bytes, *, filename: str = "customer.webm", content_type: str = "audio/webm") -> Transcription:
        self.calls.append(audio)
        assert filename.endswith(".webm")
        assert content_type == "audio/webm"
        if self.fail:
            raise RuntimeError("provider diagnostic must not reach the client")
        return Transcription(self.transcript, "en-IN")


class FakeTTS:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("provider diagnostic must not reach the client")
        return b"RIFF-test-wav"


class FakeLLM:
    provider_name = "fake"
    model_name = "unit-test"

    def __init__(self, intent: Intent = Intent.APP_UPDATE_ISSUE, *, fail: bool = False) -> None:
        self.intent = intent
        self.fail = fail
        self.calls: list[str] = []

    def classify(self, text: str) -> IntentProposal:
        self.calls.append(text)
        if self.fail:
            raise TimeoutError("private provider details")
        return IntentProposal(intent=self.intent, confidence=0.99)


def voice_request(client: TestClient, session_id: str) -> dict:
    response = client.post(
        "/api/v1/voice/turn",
        data={"session_id": session_id},
        files={"audio": ("utterance.webm", b"mock audio bytes", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_client(repository, stt, tts, llm=None):
    app = create_app(repository, llm_provider=llm or FakeLLM(), stt_provider=stt, tts_provider=tts)
    return TestClient(app)


def create_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions", json={"customer_ref": "CUST001"})
    assert response.status_code == 200
    return response.json()["session_id"]


def test_voice_audio_transcript_runs_through_kural_and_returns_audio(repository) -> None:
    stt, tts, llm = FakeSTT(), FakeTTS(), FakeLLM()
    client = make_client(repository, stt, tts, llm)
    session_id = create_session(client)

    result = voice_request(client, session_id)

    assert result["transcript"] == "My banking app is not updating"
    assert result["intent"] == Intent.APP_UPDATE_ISSUE.value
    assert result["state"] == State.IDENTITY_CHECK.value
    assert result["audio_base64"]
    assert result["audio_content_type"] == "audio/mpeg"
    assert len(stt.calls) == 1 and len(tts.calls) == 1 and len(llm.calls) == 1


def test_voice_stt_failure_does_not_advance_session_or_call_tts(repository) -> None:
    stt, tts = FakeSTT(fail=True), FakeTTS()
    client = make_client(repository, stt, tts)
    session_id = create_session(client)

    response = client.post(
        "/api/v1/voice/turn", data={"session_id": session_id},
        files={"audio": ("utterance.webm", b"mock audio bytes", "audio/webm")},
    )

    assert response.status_code == 502
    assert "provider diagnostic" not in response.text
    assert repository.get_session_detail(session_id)["turns"] == []
    assert tts.calls == []


def test_gemini_failure_uses_existing_deterministic_fallback(repository) -> None:
    stt, tts, llm = FakeSTT("My app is not updating"), FakeTTS(), FakeLLM(fail=True)
    client = make_client(repository, stt, tts, llm)
    session_id = create_session(client)

    result = voice_request(client, session_id)

    assert result["intent"] == Intent.UPDATE_FAILURE.value
    assert result["state"] == State.IDENTITY_CHECK.value
    assert len(llm.calls) == 1
    assert result["audio_base64"]


def test_tts_failure_keeps_kural_text_response_available(repository) -> None:
    stt, tts = FakeSTT(), FakeTTS(fail=True)
    client = make_client(repository, stt, tts)
    session_id = create_session(client)

    result = voice_request(client, session_id)

    assert result["response"]
    assert result["transcript"] == stt.transcript
    assert result["audio_base64"] is None
    assert "provider diagnostic" not in result["tts_error"]


def test_sensitive_voice_transcript_is_redacted_before_gemini_and_persistence(repository) -> None:
    stt = FakeSTT("My OTP is 123456")
    llm = FakeLLM()
    client = make_client(repository, stt, FakeTTS(), llm)
    session_id = create_session(client)

    result = voice_request(client, session_id)

    assert result["policy_decision"] == "BLOCKED"
    assert not result["ended"]
    assert "[REDACTED_OTP]" in result["transcript"]
    assert "123456" not in result["transcript"]
    assert llm.calls == []
    assert "123456" not in str(repository.get_session_detail(session_id))
    assert "123456" not in str(repository.list_audit_events(session_id))


def test_voice_turn_operates_on_existing_session(repository) -> None:
    stt = FakeSTT("hello")
    client = make_client(repository, stt, FakeTTS())
    session_id = create_session(client)

    result = voice_request(client, session_id)

    assert result["session_id"] == session_id
    assert repository.get_session(session_id).state == State.IDENTITY_CHECK


def test_voice_issue_confirmation_still_creates_case(repository) -> None:
    llm = FakeLLM(fail=True)
    stt = FakeSTT("yes please")
    client = make_client(repository, stt, FakeTTS(), llm)
    session_id = create_session(client)
    engine = KuralEngine(repository, llm_provider=llm)
    for text in ("yes", "yes", "yes", "the app is installed", "update failed"):
        engine.turn(session_id, text)

    result = voice_request(client, session_id)

    assert result["case_id"]
    assert result["callback_id"]
    assert repository.list_cases()[0]["session_id"] == session_id


def test_voice_callback_booking_still_creates_callback(repository) -> None:
    llm = FakeLLM(fail=True)
    stt = FakeSTT("yes, call me back")
    client = make_client(repository, stt, FakeTTS(), llm)
    session_id = create_session(client)
    engine = KuralEngine(repository, llm_provider=llm)
    for text in ("yes", "yes", "I'm busy"):
        engine.turn(session_id, text)

    result = voice_request(client, session_id)

    callbacks = repository.list_callbacks(session_id)
    assert result["callback_id"]
    assert len(callbacks) == 1
    assert callbacks[0]["session_id"] == session_id


def test_voice_busy_interrupts_identity_check_and_requests_callback(repository) -> None:
    stt, tts, llm = FakeSTT("I'm busy now, call later"), FakeTTS(), FakeLLM(Intent.AFFIRM)
    client = make_client(repository, stt, tts, llm)
    session_id = create_session(client)
    engine = KuralEngine(repository, llm_provider=llm)
    engine.turn(session_id, "yes")
    llm.calls.clear()

    result = voice_request(client, session_id)

    assert result["intent"] == Intent.BUSY.value
    assert result["callback_id"]
    assert result["ended"]
    assert llm.calls == []


class StreamingFakeTTS(FakeTTS):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(fail=fail)

    async def stream(self, text: str):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("provider diagnostics are private")
        yield b"mp3-chunk-one"
        yield b"mp3-chunk-two"


def test_websocket_voice_endpoint_streams_audio_chunks(repository) -> None:
    stt, tts = FakeSTT(), StreamingFakeTTS()
    client = make_client(repository, stt, tts)
    session_id = create_session(client)

    with client.websocket_connect("/api/v1/voice/turn/stream") as socket:
        socket.send_json({"type": "start", "session_id": session_id, "content_type": "audio/webm"})
        socket.send_bytes(b"mock voice audio")
        metadata = socket.receive_json()
        first_chunk = socket.receive_bytes()
        second_chunk = socket.receive_bytes()
        complete = socket.receive_json()

    assert metadata["type"] == "metadata"
    assert metadata["data"]["session_id"] == session_id
    assert first_chunk == b"mp3-chunk-one"
    assert second_chunk == b"mp3-chunk-two"
    assert complete["type"] == "audio_complete"


def test_websocket_tts_failure_still_returns_response_text(repository) -> None:
    stt, tts = FakeSTT(), StreamingFakeTTS(fail=True)
    client = make_client(repository, stt, tts)
    session_id = create_session(client)

    with client.websocket_connect("/api/v1/voice/turn/stream") as socket:
        socket.send_json({"type": "start", "session_id": session_id, "content_type": "audio/webm"})
        socket.send_bytes(b"mock voice audio")
        metadata = socket.receive_json()
        failure = socket.receive_json()
        complete = socket.receive_json()

    assert metadata["type"] == "metadata"
    assert metadata["data"]["response"]
    assert failure["type"] == "tts_error"
    assert "provider diagnostics" not in str(failure)
    assert complete["type"] == "audio_complete"
