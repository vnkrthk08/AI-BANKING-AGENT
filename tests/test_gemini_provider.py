from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.providers.gemini import GeminiAdapter
from kural.providers.schemas import IntentProposal


class FakeModels:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.call: dict[str, Any] | None = None

    def generate_content(self, **kwargs: Any) -> Any:
        self.call = kwargs
        if self.error:
            raise self.error
        return self.response


class FakeProvider:
    provider_name = "mock-gemini"
    model_name = "test-model"

    def __init__(self, proposal: Any = None, error: Exception | None = None) -> None:
        self.proposal = proposal
        self.error = error
        self.calls: list[str] = []

    def classify(self, text: str) -> Any:
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.proposal(text) if callable(self.proposal) else self.proposal


@pytest.mark.parametrize(
    ("intent", "utterance"),
    [
        (Intent.APP_UPDATE_ISSUE, "My banking app is not updating"),
        (Intent.BUSY, "I am driving and cannot talk"),
        (Intent.WANTS_HUMAN, "Please let me speak to a person"),
    ],
)
def test_gemini_structured_intent_proposals(intent: Intent, utterance: str) -> None:
    models = FakeModels(SimpleNamespace(parsed={"intent": intent.value, "confidence": 0.96}))
    adapter = GeminiAdapter(api_key="unit-test-key", model="test-model", client=SimpleNamespace(models=models))

    proposal = adapter.classify(utterance)

    assert proposal == IntentProposal(intent=intent, confidence=0.96)
    assert models.call is not None
    assert models.call["model"] == "test-model"
    assert models.call["config"]["response_mime_type"] == "application/json"
    assert models.call["config"]["response_json_schema"] == IntentProposal.model_json_schema()
    assert models.call["config"]["automatic_function_calling"] == {"disable": True}
    assert "no response" not in models.call["contents"].lower()


def test_unknown_intent_fails_schema_validation() -> None:
    adapter = GeminiAdapter(
        api_key="unit-test-key", model="test-model",
        client=SimpleNamespace(models=FakeModels(SimpleNamespace(parsed={"intent": "UNKNOWN", "confidence": 0.8}))),
    )
    with pytest.raises(ValidationError):
        adapter.classify("I need help")


def test_malformed_gemini_output_fails_schema_validation() -> None:
    adapter = GeminiAdapter(
        api_key="unit-test-key", model="test-model",
        client=SimpleNamespace(models=FakeModels(SimpleNamespace(parsed=None, text="not-json"))),
    )
    with pytest.raises(ValidationError):
        adapter.classify("I need help")


def test_sensitive_policy_only_intent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentProposal(intent=Intent.SENSITIVE_DATA, confidence=0.99)


def test_gemini_api_exception_uses_deterministic_fallback(repository: SqlAlchemyKuralRepository) -> None:
    provider = FakeProvider(error=TimeoutError("request details are deliberately not logged"))
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()

    result = engine.turn(session.session_id, "My app is not updating")

    assert result.intent == Intent.UPDATE_FAILURE
    assert len(provider.calls) == 1
    assert result.state == State.IDENTITY_CHECK


def test_missing_api_key_uses_deterministic_fallback(repository: SqlAlchemyKuralRepository) -> None:
    provider = GeminiAdapter(api_key=None, model="test-model")
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")

    result = engine.turn(session.session_id, "I am busy and will call later")

    assert result.intent == Intent.BUSY
    assert result.state == State.CALLBACK_BOOKING


def test_sensitive_input_is_blocked_before_provider_call(repository: SqlAlchemyKuralRepository) -> None:
    provider = FakeProvider(proposal={"intent": "AFFIRM", "confidence": 0.99})
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()

    result = engine.turn(session.session_id, "My OTP is 654321")

    assert result.intent == Intent.SENSITIVE_DATA
    assert not result.ended
    assert provider.calls == []


def test_provider_output_cannot_supply_an_action_or_skip_the_fsm(repository: SqlAlchemyKuralRepository) -> None:
    provider = FakeProvider(proposal={
        "intent": Intent.APP_UPDATE_ISSUE.value,
        "confidence": 0.99,
        "action": "CREATE_CASE_AND_CALLBACK",
        "target_state": "CASE_CREATION",
    })
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()

    result = engine.turn(session.session_id, "hello")

    assert result.intent == Intent.OTHER  # invalid proposal falls back to the phrase rules
    assert result.state == State.IDENTITY_CHECK  # KURAL's disclosure state decides the next step
    assert repository.list_cases() == []
    assert repository.list_callbacks(session.session_id) == []


def test_valid_provider_intent_is_still_interpreted_by_kural_fsm(repository: SqlAlchemyKuralRepository) -> None:
    def scripted_proposal(text: str) -> IntentProposal:
        if text == "yes":
            return IntentProposal(intent=Intent.AFFIRM, confidence=0.97)
        if text == "the app is installed":
            return IntentProposal(intent=Intent.APP_INSTALLED, confidence=0.97)
        return IntentProposal(intent=Intent.APP_UPDATE_ISSUE, confidence=0.97)

    provider = FakeProvider(proposal=scripted_proposal)
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()
    # Move deterministically into UPDATE_HELP, then let KURAL interpret the proposal.
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "the app is installed")

    result = engine.turn(session.session_id, "the screen is blank")

    assert result.intent == Intent.APP_UPDATE_ISSUE
    assert result.state == State.ISSUE_CAPTURE
    assert result.case_id is None
    assert result.callback_id is None


def test_gemini_adapter_does_not_send_more_than_the_utterance() -> None:
    models = FakeModels(SimpleNamespace(parsed={"intent": "APP_UPDATE_ISSUE", "confidence": 0.96}))
    adapter = GeminiAdapter(api_key="unit-test-key", model="test-model", client=SimpleNamespace(models=models))

    adapter.classify("app is not updating")

    assert models.call is not None
    prompt = models.call["contents"]
    assert "CUST" not in prompt
    assert "phone" not in prompt.lower()
    assert "balance" not in prompt.lower()
    assert "app is not updating" in prompt


def test_explicit_customer_name_is_redacted_before_provider(repository: SqlAlchemyKuralRepository) -> None:
    provider = FakeProvider(proposal=IntentProposal(intent=Intent.APP_UPDATE_ISSUE, confidence=0.96))
    engine = KuralEngine(repository, llm_provider=provider)
    session, _ = engine.create_session()

    engine.turn(session.session_id, "My name is Riya and my banking app is not updating")

    assert len(provider.calls) == 1
    assert "Riya" not in provider.calls[0]
    assert "[REDACTED NAME]" in provider.calls[0]
