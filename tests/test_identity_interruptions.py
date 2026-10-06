from datetime import datetime, timezone

import pytest

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.providers.schemas import IntentProposal


class AffirmingProvider:
    provider_name = "mock"
    model_name = "identity-regression"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def classify(self, text: str) -> IntentProposal:
        self.calls.append(text)
        return IntentProposal(intent=Intent.AFFIRM, confidence=0.99)


def identity_session(repository):
    provider = AffirmingProvider()
    engine = KuralEngine(repository, llm_provider=provider)
    conversation, _ = engine.create_session()
    engine.turn(conversation.session_id, "yes")
    assert repository.get_session(conversation.session_id).state == State.IDENTITY_CHECK
    provider.calls.clear()
    return engine, conversation.session_id, provider


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    [
        ("I'm busy now, call later.", Intent.BUSY),
        ("I'm busy.", Intent.BUSY),
        ("I can't talk right now.", Intent.BUSY),
        ("Call me later.", Intent.BUSY),
        ("Not now, call tomorrow.", Intent.BUSY),
        ("Call me tomorrow at 5.", Intent.CALLBACK),
    ],
)
def test_identity_check_deferral_immediately_records_callback(repository, text, expected_intent) -> None:
    engine, session_id, provider = identity_session(repository)

    result = engine.turn(session_id, text)

    assert result.intent == expected_intent
    assert result.ended
    assert result.callback_id is not None
    assert "callback" in result.response.casefold()
    assert repository.list_callbacks(session_id)[0]["requested_at"] is None
    assert provider.calls == []


def test_identity_callback_uses_explicit_requested_time_without_invention(repository) -> None:
    engine, session_id, _ = identity_session(repository)
    requested_at = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)

    result = engine.turn(session_id, "Call me tomorrow", requested_at=requested_at)

    callback = repository.list_callbacks(session_id)[0]
    assert result.callback_id == callback["callback_id"]
    assert callback["requested_at"] == requested_at


def test_identity_wrong_party_still_ends_without_callback(repository) -> None:
    engine, session_id, provider = identity_session(repository)

    result = engine.turn(session_id, "No, this isn't the customer")

    assert result.ended
    assert result.callback_id is None
    assert repository.list_callbacks(session_id) == []
    assert provider.calls == []


def test_identity_opt_out_still_uses_opt_out_state(repository) -> None:
    engine, session_id, provider = identity_session(repository)

    result = engine.turn(session_id, "Stop calling me")

    assert result.intent == Intent.OPT_OUT
    assert result.state == State.OPT_OUT
    assert repository.list_callbacks(session_id) == []
    assert provider.calls == []


def test_identity_sensitive_input_is_blocked_before_provider(repository) -> None:
    engine, session_id, provider = identity_session(repository)

    result = engine.turn(session_id, "My OTP is 123456")

    assert result.intent == Intent.SENSITIVE_DATA
    assert result.policy_decision == "BLOCKED"
    assert provider.calls == []
    assert repository.list_callbacks(session_id) == []
    assert "123456" not in str(repository.get_session_detail(session_id))
