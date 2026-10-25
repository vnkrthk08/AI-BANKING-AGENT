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
    # A requested time is retained only when the current calling policy allows it.
    # In particular, "tomorrow" can land outside permitted calling hours or on a
    # restricted day, in which case KURAL still records the callback without a time.
    requested_at = repository.list_callbacks(session_id)[0]["requested_at"]
    if requested_at is not None:
        from kural.policy.calling_policy import evaluate_contact_time
        assert evaluate_contact_time(requested_at)
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


def test_no_to_convenient_time_offers_callback_without_ending(repository) -> None:
    engine = KuralEngine(repository, llm_provider=AffirmingProvider())
    conversation, _ = engine.create_session()
    engine.turn(conversation.session_id, "yes")
    permission = engine.turn(conversation.session_id, "yes")
    assert permission.state == State.PERMISSION
    engine.llm_provider.calls.clear()

    result = engine.turn(conversation.session_id, "No")

    assert result.state == State.CALLBACK_BOOKING
    assert result.ended is False
    assert "callback" in result.response.lower()
    assert result.callback_id is None
    assert engine.llm_provider.calls == []


@pytest.mark.parametrize("not_installed_reply", ["No", "I haven't installed it"])
def test_app_installation_and_working_no_replies_continue_without_llm(repository, not_installed_reply) -> None:
    engine = KuralEngine(repository, llm_provider=AffirmingProvider())
    conversation, _ = engine.create_session()

    # Move to the app installation question using deterministic customer answers.
    engine.turn(conversation.session_id, "yes")
    engine.turn(conversation.session_id, "yes")
    app_status = engine.turn(conversation.session_id, "yes")
    assert app_status.state == State.APP_STATUS
    engine.llm_provider.calls.clear()

    not_installed = engine.turn(conversation.session_id, not_installed_reply)

    assert not_installed.state == State.UPDATE_HELP
    assert not_installed.ended is False
    assert "Google Play" in not_installed.response
    assert "Apple App Store" in not_installed.response
    assert "works properly" in not_installed.response

    not_working = engine.turn(conversation.session_id, "No, it isn't working")

    assert not_working.state == State.ISSUE_CAPTURE
    assert not_working.ended is False
    assert "support team" in not_working.response
    assert engine.llm_provider.calls == []

    declined_support = engine.turn(conversation.session_id, "No")
    assert declined_support.ended is True
    assert declined_support.state == State.ENDED
    assert engine.llm_provider.calls == []
