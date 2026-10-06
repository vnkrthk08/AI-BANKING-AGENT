"""Property-based tests for sensitive data redaction and warn-and-continue policy."""

import re
from hypothesis import given, strategies as st, settings
import pytest

from kural.privacy.redactor import (
    normalise_spoken_digits,
    redact_sensitive_data,
    detect_sensitive_partial,
    is_luhn_valid,
)
from kural.privacy.transcript import safe_transcript
from kural.policy.safety import inspect_input
from kural.conversation.engine import KuralEngine
from kural.models import Intent, State
from kural.persistence.repository import SqlAlchemyKuralRepository


# Strategy for generating 4-8 digit OTPs
otp_strategy = st.integers(min_value=1000, max_value=99999999).map(str)
# Strategy for generating 4-6 digit PINs
pin_strategy = st.integers(min_value=1000, max_value=999999).map(str)
# Strategy for generating random text wrappers
surrounding_text = st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Zs')), min_size=1, max_size=30)


@given(otp=otp_strategy, prefix=surrounding_text, suffix=surrounding_text)
@settings(max_examples=50)
def test_otp_never_leaks(otp: str, prefix: str, suffix: str):
    sentence = f"{prefix.strip()} my otp is {otp} {suffix.strip()}".strip()
    result = redact_sensitive_data(sentence)
    assert result.sensitive_present is True
    assert "OTP" in result.sensitive_types
    # Raw OTP must never appear in redacted text
    assert otp not in result.redacted_text
    assert "[REDACTED_OTP]" in result.redacted_text


@given(pin=pin_strategy, prefix=surrounding_text, suffix=surrounding_text)
@settings(max_examples=50)
def test_pin_never_leaks(pin: str, prefix: str, suffix: str):
    sentence = f"{prefix.strip()} my pin is {pin} {suffix.strip()}".strip()
    result = redact_sensitive_data(sentence)
    assert result.sensitive_present is True
    assert "PIN" in result.sensitive_types
    # Raw PIN must never appear in redacted text
    assert pin not in result.redacted_text
    assert "[REDACTED_PIN]" in result.redacted_text


def test_spoken_digits_normalization():
    assert normalise_spoken_digits("four eight two nine one three") == "482913"
    assert normalise_spoken_digits("double five") == "55"
    assert normalise_spoken_digits("triple zero") == "000"
    assert normalise_spoken_digits("double five double zero") == "55 00"
    
    # Combined with OTP context
    res = redact_sensitive_data("my otp is four eight two nine one three")
    assert res.sensitive_present is True
    assert "482913" not in res.redacted_text
    assert "[REDACTED_OTP]" in res.redacted_text


def test_spoken_pin_redaction():
    res = redact_sensitive_data("my pin is double five double zero")
    assert res.sensitive_present is True
    assert "5500" not in res.redacted_text
    assert "[REDACTED_PIN]" in res.redacted_text


def test_pan_and_card_redaction():
    pan_text = "my pan is ABCDE1234F"
    res = redact_sensitive_data(pan_text)
    assert res.sensitive_present is True
    assert "ABCDE1234F" not in res.redacted_text
    assert "[REDACTED_ID]" in res.redacted_text

    card_text = "my card number is 4111 1111 1111 1111"
    res_card = redact_sensitive_data(card_text)
    assert res_card.sensitive_present is True
    assert "4111" not in res_card.redacted_text
    assert "[REDACTED_CARD]" in res_card.redacted_text


def test_partial_transcript_detection_triggers_interrupt():
    assert detect_sensitive_partial("my otp is 4") is True
    assert detect_sensitive_partial("my pin is") is True
    assert detect_sensitive_partial("hello how are you") is False


from kural.persistence.database import Database
from kural.persistence.models import Base


def _make_repo() -> SqlAlchemyKuralRepository:
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    return SqlAlchemyKuralRepository(db)


def test_sensitive_warn_and_continue_does_not_end_call():
    repo = _make_repo()
    engine = KuralEngine(repo)
    session, _ = engine.create_session("demo-001")
    engine.begin_live_call(session.session_id)

    # Turn 1: customer gives OTP
    res1 = engine.turn(session.session_id, "my otp is 482913")
    assert res1.ended is False
    assert res1.state == State.IDENTITY_CHECK  # Call didn't end!
    assert "482913" not in res1.response
    assert "Please don't share your OTP" in res1.response
    assert "we can carry on" in res1.response

    # Verify DB has no secret
    detail = repo.get_session_detail(session.session_id)
    events = repo.list_audit_events(session.session_id)
    assert "482913" not in str(detail)
    assert "482913" not in str(events)

    # Turn 2: customer gives PIN (2nd time)
    res2 = engine.turn(session.session_id, "my pin is 1234")
    assert res2.ended is False
    assert "Just a reminder" in res2.response
    assert "1234" not in str(repo.get_session_detail(session.session_id))

    # Turn 3: 3rd time gives secret -> includes advice to change
    res3 = engine.turn(session.session_id, "my password is secret123")
    assert res3.ended is False
    assert "it's a good idea to change it" in res3.response


def test_sensitive_with_intent_continues_call_and_applies_intent():
    repo = _make_repo()
    engine = KuralEngine(repo)
    session, _ = engine.create_session("demo-001")
    engine.begin_live_call(session.session_id)

    # "yes speaking and my otp is 482913"
    res = engine.turn(session.session_id, "yes speaking and my otp is 482913")
    assert res.ended is False
    assert "482913" not in str(repo.get_session_detail(session.session_id))
    # It should have warned AND confirmed identity
    assert "Please don't share your OTP" in res.response
    assert res.state == State.PERMISSION
