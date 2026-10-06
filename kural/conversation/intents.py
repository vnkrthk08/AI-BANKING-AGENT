"""Deterministic intent detection for the limited demo call."""

import re

from kural.models import Intent

MIN_INTENT_CONFIDENCE = 0.45


def _contains_phrase(text: str, phrase: str) -> bool:
    """Match complete words so e.g. `no` cannot match inside `know`."""
    words = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.search(rf"(?<!\w){words}(?!\w)", text) is not None


def detect_intent(text: str, confidence: float = 1.0) -> Intent:
    t = text.casefold().strip()
    if not t:
        return Intent.SILENCE
    if confidence < MIN_INTENT_CONFIDENCE:
        return Intent.LOW_CONFIDENCE
    rules = [
        (Intent.FRAUD_REPORT, ("fraud", "scam", "someone stole", "unauthorized", "not me")),
        (Intent.OPT_OUT, ("stop calling", "do not call", "don't call", "opt out", "remove me")),
        (Intent.WANTS_HUMAN, ("human", "person", "agent", "representative", "real person", "speak to")),
        (Intent.ASKS_IF_AI, ("are you ai", "are you a bot", "automated", "robot")),
        (Intent.ASKS_IDENTITY, ("who are you", "which bank", "why are you calling", "what is this about")),
        (Intent.TRUST_CONCERN, ("don't trust", "do not trust", "suspicious", "is this legitimate", "verify this")),
        (Intent.LANGUAGE_SWITCH, ("speak tamil", "speak hindi", "change language", "in tamil", "in hindi")),
        (Intent.ABUSE, ("you idiot", "shut up", "you are stupid")),
        (Intent.OUT_OF_SCOPE, ("balance", "statement", "transfer money", "credit score", "loan approval")),
        (Intent.BUSY, ("busy", "not now", "can't talk", "cannot talk", "call later", "call me later", "driving", "driving right now")),
        (Intent.UPDATE_FAILURE, ("failed", "error", "problem", "not updating", "isn't updating", "is not updating", "can't update", "cannot update")),
        (Intent.UPDATE_SUCCESS, ("updated", "update complete", "done updating", "installed the update")),
        (Intent.APP_NOT_INSTALLED, ("not installed", "don't have the app", "do not have the app")),
        (Intent.APP_INSTALLED, ("have the app", "app is installed", "yes, installed", "yes installed")),
        (Intent.CALLBACK, ("callback", "call me", "later today", "tomorrow")),
        (Intent.AFFIRM, ("yes", "yeah", "sure", "okay", "ok", "correct", "speaking", "yes speaking", "yes, speaking", "this is he", "this is she", "yes i am", "i am", "myself")),
        (Intent.NEGATE, ("no", "nope", "not interested")),
    ]
    for intent, phrases in rules:
        if any(_contains_phrase(t, phrase) for phrase in phrases):
            return intent
    return Intent.OTHER


def detect_identity_interruption(text: str, confidence: float = 1.0) -> Intent | None:
    """Recognize safety/deferral intents that must interrupt identity confirmation."""
    intent = detect_intent(text, confidence)
    if intent in {Intent.OPT_OUT, Intent.FRAUD_REPORT}:
        return intent

    # A clear wrong-party statement must remain an end flow even if it also
    # contains a generic callback phrase.
    normalized = text.casefold()
    wrong_party_phrases = (
        "not the customer", "not the intended customer", "not customer",
        "wrong person", "wrong number", "you have the wrong", "isn't the customer",
        "is not the customer", "isn't the intended customer", "is not the intended customer",
    )
    if any(_contains_phrase(normalized, phrase) for phrase in wrong_party_phrases):
        return Intent.NEGATE

    if intent in {Intent.BUSY, Intent.CALLBACK, Intent.WANTS_HUMAN}:
        return intent
    if intent == Intent.NEGATE:
        return Intent.NEGATE
    return None

