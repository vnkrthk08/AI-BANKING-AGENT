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
        (Intent.FRAUD_REPORT, ("fraud", "scam", "someone stole", "unauthorized", "not me", "hacked", "stolen")),
        (Intent.OPT_OUT, ("stop calling", "do not call", "don't call", "opt out", "remove me", "unsubscribe")),
        (Intent.WANTS_HUMAN, ("human", "person", "agent", "representative", "real person", "speak to a person", "connect to agent", "talk to human")),
        (Intent.ASKS_IF_AI, ("are you an ai", "an ai", "is this an ai", "are you ai", "are you a bot", "automated", "robot", "is this ai", "are you computer")),
        (Intent.ASKS_IDENTITY, ("who are you", "which bank", "why are you calling", "what is this about", "who is speaking", "who is this")),
        (Intent.TRUST_CONCERN, ("don't trust", "do not trust", "suspicious", "is this legitimate", "verify this", "fake call")),
        (Intent.LANGUAGE_SWITCH, ("speak tamil", "speak hindi", "change language", "in tamil", "in hindi", "tamil please", "hindi please")),
        (Intent.ABUSE, ("you idiot", "shut up", "you are stupid", "fool")),
        (Intent.OUT_OF_SCOPE, ("balance", "statement", "transfer money", "credit score", "loan approval", "check balance")),
        (Intent.BUSY, ("busy", "not now", "can't talk", "cant talk", "cannot talk", "call later", "call me later", "call back", "driving", "driving right now", "in a meeting", "meeting", "at work", "working", "traveling", "travelling", "call tomorrow", "later please")),
        (Intent.UPDATE_FAILURE, (
            "trouble logging in", "having trouble", "trouble", "can't log in", "cannot log in", "logging in",
            "failed", "error", "problem", "not updating", "isn't updating", "is not updating", "can't update",
            "cannot update", "issue with update", "download failed", "issue", "keeps loading", "not loading",
            "crashes", "crash", "crashing", "crashed", "not recognized", "not recognised", "not working", "freezes", "frozen", "stuck"
        )),
        (Intent.UPDATE_SUCCESS, ("updated", "update complete", "done updating", "installed the update", "already updated", "finished updating")),
        (Intent.APP_NOT_INSTALLED, (
            "not installed", "don't have the app", "do not have the app", "haven't installed", "not downloaded",
            "only use the website", "use the website", "netbanking", "net banking", "on my computer", "on my laptop", "deleted it"
        )),
        (Intent.APP_INSTALLED, ("using the app", "use the app", "been using", "use it", "using it", "have the app", "app is installed", "yes, installed", "yes installed", "installed", "already have")),
        (Intent.CALLBACK, ("callback", "call me", "later today", "tomorrow", "call after", "call evening", "call morning", "call afternoon", "schedule a call", "reschedule", "call at")),
        (Intent.AFFIRM, (
            "yes", "yeah", "yep", "sure", "okay", "ok", "correct", "speaking", "yes speaking", "yes, speaking",
            "this is he", "this is she", "yes i am", "i am", "myself", "yes please", "yeah please", "sure please",
            "ok please", "i can talk", "can talk", "go ahead", "that's fine", "thats fine", "fine", "yes tell me",
            "tell me", "alright", "all right", "i am available", "available", "carry on", "proceed", "yes i do",
            "i do", "yes i have", "i have", "yes sure"
        )),
        (Intent.NEGATE, ("no", "nope", "not interested", "no thanks", "not now thanks")),
    ]
    for intent, phrases in rules:
        if any(_contains_phrase(t, phrase) for phrase in phrases):
            return intent
    return Intent.OTHER


def detect_side_question(text: str) -> str | None:
    t = text.casefold().strip()
    if any(_contains_phrase(t, phrase) for phrase in (
        "what does the app do", "app features", "what can it do", "what is this app for",
        "what can i do", "why should i use it", "what is the app", "what can i use it for",
        "what does it do", "what are the features"
    )):
        return "APP_FEATURES"
    if any(_contains_phrase(t, phrase) for phrase in ("is it safe", "is this safe", "is it secure", "security", "safe to use")):
        return "IS_IT_SAFE"
    if any(_contains_phrase(t, phrase) for phrase in (
        "is it free", "is this free", "any charge", "free of charge", "does it cost",
        "is the update free", "is this update free", "any fees"
    )):
        return "IS_IT_FREE"
    if any(_contains_phrase(t, phrase) for phrase in (
        "what's new", "whats new", "latest version", "new version", "new in this version",
        "new in the latest", "new features", "version 5", "version number"
    )):
        return "WHAT_IS_NEW"
    if any(_contains_phrase(t, phrase) for phrase in ("who are you", "who is this", "what is your name")):
        return "WHO_ARE_YOU"
    if any(_contains_phrase(t, phrase) for phrase in ("why are you calling", "why calling")):
        return "WHY_CALLING"
    return None


def detect_issue_details(text: str) -> tuple[bool, str | None, str | None]:
    """Extract (issue_present, category, description) deterministically without inventing claims."""
    t = text.casefold().strip()
    if not t:
        return False, None, None

    issue_indicators = (
        "keeps loading", "not loading", "loading problem", "fails", "failed", "failing",
        "error", "problem", "trouble", "crashes", "crash", "crashing", "crashed", "not working",
        "won't work", "wont work", "closes", "force close", "not recognized", "not recognised",
        "can't", "cannot", "stuck", "frozen", "doesn't open", "does not open", "won't open",
        "download failed", "transaction failed"
    )
    has_explicit_indicator = any(_contains_phrase(t, ind) for ind in issue_indicators)

    if not has_explicit_indicator:
        return False, None, None

    if any(_contains_phrase(t, p) for p in ("biometric", "fingerprint", "face id", "faceid", "touch id")):
        return True, "BIOMETRIC", "biometric sensor recognition failure"
    if any(_contains_phrase(t, p) for p in ("log in", "login", "logging in", "password", "mpin", "sign in", "signing in")):
        return True, "LOGIN", "login authentication problem"
    if any(_contains_phrase(t, p) for p in ("payment", "upi", "transfer money", "sending money", "transaction")):
        return True, "PAYMENT", "payment loading failure"
    if any(_contains_phrase(t, p) for p in ("crash", "crashed", "crashing", "closes", "force close", "not updating", "download failed", "won't update")):
        return True, "UPDATE_CRASH", "app update or crash error"
    if any(_contains_phrase(t, p) for p in ("network error", "no internet", "server error", "connection timed out", "connection error")):
        return True, "NETWORK", "network connection timeout"

    return True, "GENERAL", "general application issue"

    return False, None, None


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

