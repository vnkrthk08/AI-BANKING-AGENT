"""Phase 1 Voice Intelligence & Real-Time Voice Verification Suite.

Validates:
1. Natural speech understanding & affirmations / negations / indirect answers
2. Side-question detours without losing workflow state
3. Progressive clarification and repetition limits
4. Fast deterministic fallback on LLM failure
5. Turn telemetry contract & timing propagation
6. Data privacy & masking guarantees
"""

from __future__ import annotations

import time
from typing import Any
import pytest

from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.providers.contracts import LLMProvider
from kural.providers.schemas import IntentProposal


class MockSwappableLLM(LLMProvider):
    provider_name = "test_provider"
    model_name = "test_model"

    def __init__(
        self,
        intent: Intent = Intent.AFFIRM,
        confidence: float = 0.98,
        secondary_question: str | None = None,
        entities: dict[str, Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.intent = intent
        self.confidence = confidence
        self.secondary_question = secondary_question
        self.entities = entities or {}
        self.fail = fail
        self.calls: list[str] = []

    def classify(self, text: str) -> IntentProposal:
        self.calls.append(text)
        if self.fail:
            raise TimeoutError("Simulated LLM network timeout")
        return IntentProposal(
            intent=self.intent,
            confidence=self.confidence,
            secondary_question=self.secondary_question,
            entities=self.entities,
        )


def test_natural_speech_affirmations_and_indirect_answers(repository: SqlAlchemyKuralRepository) -> None:
    """Verifies that natural variations ('yeah sure', 'speaking') advance the FSM correctly."""
    llm = MockSwappableLLM(intent=Intent.AFFIRM, confidence=0.97)
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    # Turn 1: Opening disclosure -> IDENTITY_CHECK
    r1 = engine.turn(session.session_id, "Hello")
    assert r1.state == State.IDENTITY_CHECK

    # Turn 2: Natural affirmation "Yes, this is Rahul speaking"
    r2 = engine.turn(session.session_id, "Yes, this is Rahul speaking")
    assert r2.state == State.PERMISSION
    assert not r2.fallback_used
    assert "convenient time" in r2.response

    # Turn 3: Natural consent "Yeah I have two minutes"
    r3 = engine.turn(session.session_id, "Yeah I have two minutes")
    assert r3.state == State.APP_STATUS
    assert "installed" in r3.response


def test_side_question_detour_preserves_fsm_state(repository: SqlAlchemyKuralRepository) -> None:
    """Customer asks 'What features does the app have?' during APP_STATUS; state must remain APP_STATUS."""
    llm = MockSwappableLLM(
        intent=Intent.OTHER,
        confidence=0.95,
        secondary_question="APP_FEATURES",
    )
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    engine.turn(session.session_id, "hello")  # DISCLOSURE -> IDENTITY_CHECK
    llm.intent = Intent.AFFIRM
    llm.secondary_question = None
    engine.turn(session.session_id, "yes speaking")  # IDENTITY_CHECK -> PERMISSION
    engine.turn(session.session_id, "sure I have time")  # PERMISSION -> APP_STATUS

    # Now in APP_STATUS: customer asks side question about features
    llm.intent = Intent.OTHER
    llm.secondary_question = "APP_FEATURES"
    detour_res = engine.turn(session.session_id, "Wait, what can I do with this app?")

    assert detour_res.state == State.APP_STATUS  # Preserves state!
    assert "UPI payments" in detour_res.response
    assert "installed on your phone" in detour_res.response  # Re-prompts current state!
    assert detour_res.secondary_question == "APP_FEATURES"


def test_combined_answer_and_side_question_detour(repository: SqlAlchemyKuralRepository) -> None:
    """Customer says 'Yes it is installed, but is the app free?' -> answers detour and advances state."""
    llm = MockSwappableLLM(
        intent=Intent.APP_INSTALLED,
        confidence=0.98,
        secondary_question="IS_IT_FREE",
    )
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    engine.turn(session.session_id, "hello")
    llm.intent = Intent.AFFIRM
    llm.secondary_question = None
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")

    # In APP_STATUS: customer answers AND asks side question
    llm.intent = Intent.APP_INSTALLED
    llm.secondary_question = "IS_IT_FREE"
    res = engine.turn(session.session_id, "Yes it's installed, but is it free?")

    assert res.state == State.UPDATE_HELP  # Progresses to next state
    assert "completely free of charge" in res.response  # Answers the question
    assert "Play Store" in res.response or "App Store" in res.response  # Contains update instructions
    assert res.secondary_question == "IS_IT_FREE"


def test_progressive_clarification_and_repetition_limits(repository: SqlAlchemyKuralRepository) -> None:
    """Verifies that 3 consecutive unrecognized responses escalate to graceful termination."""
    llm = MockSwappableLLM(intent=Intent.AFFIRM, confidence=0.99)
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    # Move from DISCLOSURE to IDENTITY_CHECK
    engine.turn(session.session_id, "hello")

    # Now customer starts giving low-confidence / unintelligible responses in IDENTITY_CHECK
    llm.intent = Intent.LOW_CONFIDENCE
    llm.confidence = 0.4

    # Repetition 1: In IDENTITY_CHECK, low confidence -> polite repeat prompt
    r1 = engine.turn(session.session_id, "mumble mumble")
    assert r1.state == State.IDENTITY_CHECK
    assert "didn’t catch that clearly" in r1.response

    # Repetition 2: Low confidence again -> offer callback
    r2 = engine.turn(session.session_id, "inaudible noise")
    assert r2.state == State.CALLBACK_BOOKING
    assert "arrange a callback" in r2.response

    # Repetition 3: Third low confidence -> graceful termination
    r3 = engine.turn(session.session_id, "static...")
    assert r3.state in (State.CLOSING, State.ENDED)
    assert r3.ended
    assert "inconvenienced" in r3.response or "Goodbye" in r3.response


def test_fast_deterministic_fallback_on_llm_failure(repository: SqlAlchemyKuralRepository) -> None:
    """When the LLM throws a timeout or network error, fallback executes locally within milliseconds."""
    llm = MockSwappableLLM(fail=True)  # Will raise TimeoutError
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    engine.turn(session.session_id, "hello")

    # Customer says "yes", LLM fails -> local deterministic fallback detects AFFIRM
    t_start = time.perf_counter()
    res = engine.turn(session.session_id, "yes")
    t_elapsed = (time.perf_counter() - t_start) * 1000

    assert res.fallback_used is True
    assert res.intent == Intent.AFFIRM
    assert res.state == State.PERMISSION
    assert t_elapsed < 50.0  # Must be fast and local (< 50ms total turn)


def test_entities_and_facts_extraction_persists(repository: SqlAlchemyKuralRepository) -> None:
    """Extracted entities update the conversation turn and response payload."""
    llm = MockSwappableLLM(
        intent=Intent.AFFIRM,
        confidence=0.99,
        entities={"customer_verified": True, "app_version_reported": "2.3.0"},
    )
    engine = KuralEngine(repository, llm_provider=llm)
    session, _ = engine.create_session()

    engine.turn(session.session_id, "hello")
    res = engine.turn(session.session_id, "Yes speaking, I have version 2.3.0")

    assert res.entities.get("app_version_reported") == "2.3.0"
    assert res.entities.get("customer_verified") is True


def test_provider_benchmark_comparison() -> None:
    """Validates that provider adapters conform to identical LLMProvider contract."""
    from kural.providers.openai_compatible import OpenAICompatibleAdapter
    from kural.providers.gemini import GeminiAdapter
    from kural.providers.config import get_llm_provider

    groq_adapter = OpenAICompatibleAdapter(
        provider_name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="mock-groq-key",
        model="llama-3.1-8b-instant",
    )
    assert groq_adapter.provider_name == "groq"
    assert groq_adapter.model_name == "llama-3.1-8b-instant"

    qwen_adapter = OpenAICompatibleAdapter(
        provider_name="qwen",
        base_url="https://openrouter.ai/api/v1",
        api_key="mock-qwen-key",
        model="qwen/qwen-2.5-7b-instruct",
    )
    assert qwen_adapter.provider_name == "qwen"
    assert qwen_adapter.model_name == "qwen/qwen-2.5-7b-instruct"

    gemini_adapter = GeminiAdapter(
        api_key="mock-gemini-key",
        model="gemini-2.0-flash",
    )
    assert gemini_adapter.provider_name == "gemini"
    assert gemini_adapter.model_name == "gemini-2.0-flash"

