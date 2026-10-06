"""Unit tests for Prompt D: Subbu NLU, Prompt Builder, and Fallback Classifier."""

import pytest
from kural.nlu import (
    PromptBuilder,
    SubbuClassifier,
    DeterministicKeywordNLU,
    NLUResult,
    assert_safe_llm_request,
)


def test_prompt_builder_selects_relevant_examples():
    builder = PromptBuilder()
    examples = builder.select_examples("PERMISSION_CHECK", max_examples=20)
    assert len(examples) <= 20
    assert len(examples) > 5

    # Build prompt
    prompt, version = builder.build_prompt(
        state="PERMISSION_CHECK",
        subbu_last_line="is now a good time for two minutes?",
        allowed_intents=["AFFIRM", "BUSY", "CALLBACK_REQUEST", "DECLINE"],
        global_intents=["OPT_OUT", "WANTS_HUMAN", "FRAUD_REPORT"],
        utterance="abhi busy hoon kal shaam ko call karna",
    )
    assert "CURRENT STATE: PERMISSION_CHECK" in prompt
    assert "abhi busy hoon kal shaam ko call karna" in prompt
    assert version == "classify.v1.txt"


def test_privacy_guard_fails_if_pii_present():
    # Attempting to send customer phone or ref to LLM must fail
    with pytest.raises(ValueError, match="PII detected"):
        assert_safe_llm_request(utterance="Hello customer 9876543210", subbu_last_line="")

    with pytest.raises(ValueError, match="PII detected"):
        assert_safe_llm_request(utterance="Account ref C48291 please check", subbu_last_line="")

    with pytest.raises(ValueError, match="Forbidden value 'Rahul'"):
        assert_safe_llm_request(utterance="yes speaking", subbu_last_line="Am I speaking with Rahul?", forbidden_strings=["Rahul"])


def test_deterministic_keyword_nlu_core_intents():
    # Affirm / Deny
    assert DeterministicKeywordNLU.classify("haan bolo", "IDENTITY_CHECK").primary_intent == "IDENTITY_CONFIRMED"
    assert DeterministicKeywordNLU.classify("yes go ahead", "PERMISSION_CHECK").primary_intent == "AFFIRM"
    assert DeterministicKeywordNLU.classify("no that's all", "ISSUE_CHECK").primary_intent == "DENY"

    # Busy / Callback
    res_cb = DeterministicKeywordNLU.classify("abhi busy hoon kal shaam ko call karna", "PERMISSION_CHECK")
    assert res_cb.primary_intent == "CALLBACK_REQUEST"
    assert "BUSY" in res_cb.secondary_intents
    assert res_cb.entities.time_expression is not None
    assert res_cb.entities.time_expression.date_text == "tomorrow"
    assert res_cb.entities.time_expression.part_of_day == "evening"

    # Fraud
    assert DeterministicKeywordNLU.classify("someone took 5000 from my account", "PERMISSION_CHECK").primary_intent == "FRAUD_REPORT"

    # Opt-Out
    assert DeterministicKeywordNLU.classify("stop calling me please", "APP_STATUS_CHECK").primary_intent == "OPT_OUT"

    # Human
    assert DeterministicKeywordNLU.classify("i don't want to talk to a bot get me a person", "UPDATE_GUIDANCE").primary_intent == "WANTS_HUMAN"

    # Cancel
    assert DeterministicKeywordNLU.classify("no forget it don't call", "CALLBACK_CONFIRMATION").primary_intent == "CANCEL"


def test_classifier_metadata_and_fallback():
    classifier = SubbuClassifier(api_key=None, model="gemini-2.5-flash")
    result = classifier.classify(
        state="PERMISSION_CHECK",
        subbu_last_line="is now a good time?",
        allowed_intents=["AFFIRM", "BUSY", "DECLINE"],
        global_intents=["OPT_OUT", "WANTS_HUMAN"],
        utterance="sure go ahead",
        forbidden_pii=["Rahul", "C48291"],
    )
    assert result.primary_intent == "AFFIRM"
    assert result.prompt_version == "classify.v1.txt"
    assert "gemini-2.5-flash" in result.model_id
