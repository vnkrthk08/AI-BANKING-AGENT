import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from kural.conversation.engine import KuralEngine
from kural.conversation.intents import detect_intent
from kural.gateway.mock_bank import MockBankGateway
from kural.models import Action, Intent, State
from kural.privacy.transcript import safe_transcript
from kural.policy.safety import authorize, inspect_input, redact
from kural.audit.events import AuditLog
from kural.repositories import KuralRepository


def advance_to_app_status(engine: KuralEngine) -> str:
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    return session.session_id


def test_session_creation(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    session, greeting = engine.create_session()
    assert session.state == State.DISCLOSURE
    assert "automated assistant" in greeting


def test_normal_app_update_flow(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    assert engine.turn(sid, "the app is installed").state == State.UPDATE_HELP
    result = engine.turn(sid, "updated, done")
    assert result.state == State.ENDED and result.ended


def test_busy_customer_can_request_callback(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    assert engine.turn(session.session_id, "I'm busy").state == State.CALLBACK_BOOKING
    result = engine.turn(session.session_id, "yes, call me back")
    assert result.ended and result.case_id is None and result.callback_id is not None
    assert "call" in result.response.lower()
    assert repository.list_cases() == []
    assert repository.list_callbacks(session.session_id)[0]["case_id"] is None
    assert any(e["event_type"] == "callback_request" for e in repository.list_audit_events(session.session_id))


def test_driving_and_call_me_later_is_busy(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    result = engine.turn(session.session_id, "I'm driving right now, call me later.")
    assert result.intent == Intent.BUSY
    assert result.state == State.CALLBACK_BOOKING


def test_human_request(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    result = engine.turn(sid, "I want a human agent")
    assert result.state == State.HUMAN_ESCALATION and result.ended
    assert "support team" in result.response


def test_opt_out(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    result = engine.turn(sid, "stop calling me")
    assert result.state == State.OPT_OUT and result.ended
    assert "not called about this again" in result.response


def test_fraud_escalation(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    result = engine.turn(sid, "I think this is a scam")
    assert result.state == State.FRAUD_ESCALATION and result.ended


def test_sensitive_data_block_is_not_stored(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    result = engine.turn(session.session_id, "My OTP is 123456")
    # Per Spec §8.1 and Prompt C: warn and continue, do NOT end call
    assert result.intent == Intent.SENSITIVE_DATA and not result.ended
    assert result.policy_decision == "BLOCKED"
    assert "123456" not in result.sanitized_user_text
    assert "[REDACTED_OTP]" in result.sanitized_user_text
    detail = repository.get_session_detail(session.session_id)
    events = repository.list_audit_events(session.session_id)
    assert "123456" not in str(detail)
    assert "123456" not in str(events)
    assert detail["current_state"] != State.ENDED.value


def test_update_failure_creates_case_and_callback(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    engine.turn(sid, "app is installed")
    engine.turn(sid, "update failed")
    result = engine.turn(sid, "yes, please")
    assert result.case_id is not None
    assert "does not place a real call" in result.response
    case = repository.list_cases()[0]
    assert case["category"] == "APP_UPDATE_FAILURE"
    assert result.callback_id is not None
    assert repository.list_callbacks(sid)[0]["case_id"] == result.case_id


def test_case_creation_audited(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    engine.turn(sid, "the app is installed")
    engine.turn(sid, "update failed")
    result = engine.turn(sid, "yes")
    assert result.state == State.ENDED and result.case_id and result.callback_id
    events = repository.list_audit_events(sid)
    assert any(e["event_type"] == "case_creation" for e in events)
    assert any(e["event_type"] == "callback_request" for e in events)
    assert any(e["metadata"].get("old") == State.ISSUE_CAPTURE.value and e["metadata"].get("new") == State.CASE_CREATION.value for e in events)


def test_redaction() -> None:
    assert redact("code 123456 sent") == "code [REDACTED] sent"
    assert redact("card 4111 1111 1111 1111") == "card [REDACTED]"
    assert "[REDACTED_PIN]" in inspect_input("My PIN: 1982").redacted_text
    assert "1982" not in inspect_input("My PIN: 1982").redacted_text
    assert "[REDACTED_SECRET]" in safe_transcript("password is hunter2")
    assert "hunter2" not in safe_transcript("password is hunter2")


def test_audit_sanitizes_customer_text_at_write_boundary() -> None:
    audit = AuditLog()
    audit.record("customer_turn", text="My password is hunter2 and code 123456")
    assert "hunter2" not in audit.events[0]["text"]
    assert "123456" not in audit.events[0]["text"]
    assert "[REDACTED_SECRET]" in audit.events[0]["text"]
    audit.record("customer_turn", note="OTP: 123456")
    assert "123456" not in audit.events[1]["note"]
    audit.record("customer_turn", text="My code is 123456")
    assert "123456" not in audit.events[2]["text"]


def test_action_authorization_is_state_specific() -> None:
    assert authorize(Action.CREATE_APP_UPDATE_CASE, State.ISSUE_CAPTURE, State.CASE_CREATION)
    assert not authorize(Action.CREATE_APP_UPDATE_CASE, State.PERMISSION, State.CASE_CREATION)
    assert authorize(Action.REQUEST_CALLBACK, State.CALLBACK_BOOKING, State.ENDED)
    assert not authorize(Action.REQUEST_CALLBACK, State.APP_STATUS, State.ENDED)


def test_gateway_allow_list() -> None:
    gateway = MockBankGateway()
    assert gateway.get_customer("demo-001", {"app_version"}) == {"app_version": "4.2.0"}
    assert gateway.get_customer("demo-001", set()) == {}
    with pytest.raises(ValueError):
        gateway.get_customer("demo-001", {"balance"})


def test_intents_match_whole_words_not_substrings() -> None:
    assert detect_intent("I don't know") == Intent.OTHER
    assert detect_intent("yesterday works") == Intent.OTHER
    assert detect_intent("the token is ready") == Intent.OTHER
    assert detect_intent("no") == Intent.NEGATE


def test_terminal_session_ignores_later_customer_text(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    result = engine.turn(sid, "stop calling me")
    event_count = len(repository.list_audit_events(sid))
    later = engine.turn(sid, "My OTP is 123456")
    assert result.state == State.OPT_OUT and result.ended
    assert later.state == State.OPT_OUT and later.ended
    assert len(repository.list_audit_events(sid)) == event_count
    assert "123456" not in str(repository.list_audit_events(sid))


def test_ordinary_endings_reach_ended_state(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    sid = advance_to_app_status(engine)
    engine.turn(sid, "the app is installed")
    result = engine.turn(sid, "updated")
    assert result.state == State.ENDED and result.ended
    transitions = [event for event in repository.list_audit_events(sid) if event["event_type"] == "state_transition"]
    assert any(event["metadata"]["old"] == State.CLOSING.value and event["metadata"]["new"] == State.ENDED.value for event in transitions)


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_page_loads() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "KURAL AVA" in response.text


def test_state_transition_correctness(repository: KuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    assert engine.turn(session.session_id, "yes").state == State.IDENTITY_CHECK
    assert engine.turn(session.session_id, "yes").state == State.PERMISSION
    assert engine.turn(session.session_id, "yes").state == State.APP_STATUS


def test_api_complete_conversation(repository: KuralRepository) -> None:
    with TestClient(create_app(repository)) as client:
        session = client.post("/api/v1/sessions").json()
        sid = session["session_id"]
        turns = ["yes", "yes", "yes", "the app is installed", "update failed", "yes"]
        result = None
        for text in turns:
            response = client.post(f"/api/v1/sessions/{sid}/messages", json={"text": text})
            assert response.status_code == 200
            result = response.json()
        assert result["ended"] is True
        assert result["case_id"]
        assert client.get(f"/api/v1/sessions/{sid}").json()["current_state"] == State.ENDED.value
        assert len(client.get("/api/v1/cases").json()) == 1
        audit = client.get(f"/api/v1/audit/{sid}").json()
        assert any(event["event_type"] == "case_creation" for event in audit)


def test_api_accepts_requested_synthetic_customer_ref(repository: KuralRepository) -> None:
    with TestClient(create_app(repository)) as client:
        response = client.post("/api/v1/sessions", json={"customer_ref": "CUST001"})
    assert response.status_code == 200
    assert response.json()["customer_ref"] == "CUST001"

