"""Subbu NLU Classifier with Gemini structured output and deterministic keyword fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional

from kural.nlu.prompt_builder import PromptBuilder, default_prompt_builder
from kural.nlu.schemas import Entities, NLUResult, TimeExpression

logger = logging.getLogger(__name__)


FORBIDDEN_PII_PATTERNS = [
    re.compile(r"\b(?:\+?91|0)?[6-9]\d{9}\b"),  # 10-digit Indian phone
    re.compile(r"\bC\d{5}\b"),  # customer refs like C48291
    re.compile(r"\bdemo-\d+\b", re.I),
]


def assert_safe_llm_request(
    utterance: str,
    subbu_last_line: str,
    last_turns: list[dict[str, str]] | None = None,
    forbidden_strings: list[str] | None = None,
) -> None:
    """Ensure dynamic LLM prompt inputs never contain customer PII or raw secrets."""
    dynamic_text = f"{utterance} {subbu_last_line}"
    if last_turns:
        for t in last_turns:
            dynamic_text += f" {t.get('text', '')}"

    for pattern in FORBIDDEN_PII_PATTERNS:
        if pattern.search(dynamic_text):
            raise ValueError("PII detected in LLM dynamic request: phone or customer ref pattern")
    if forbidden_strings:
        for s in forbidden_strings:
            if s and re.search(r"\b" + re.escape(s) + r"\b", dynamic_text, re.IGNORECASE):
                raise ValueError(f"Forbidden value '{s}' detected in LLM request")


class DeterministicKeywordNLU:
    """Fallback keyword classifier for core intents (English + Hinglish)."""

    @classmethod
    def classify(cls, utterance: str, state: str = "PERMISSION_CHECK") -> NLUResult:
        u = f" {utterance.lower().strip()} "

        # Global 1: Fraud Report (Unauthorized transaction / money stolen / OTP compromised)
        fraud_keywords = ["hacked", "stolen", "unauthorized", "chori", "paise kat gaye", "gave my otp", "shared my otp", "someone took money"]
        if any(w in u for w in fraud_keywords) or ("took" in u and "account" in u) or ("money" in u and ("account" in u or "took" in u)):
            secondary = ["OPT_OUT"] if ("stop" in u or "don't call" in u) else []
            return NLUResult(primary_intent="FRAUD_REPORT", secondary_intents=secondary, confidence=0.96)

        # Global 2: Trust Concern
        trust_keywords = ["scam call", "fake call", "is this a scam", "fraud call", "real bank", "really town bank", "why should i tell you", "steal my money"]
        if any(w in u for w in trust_keywords) or ("scam" in u and ("call" in u or "this" in u)):
            return NLUResult(primary_intent="TRUST_CONCERN", confidence=0.96)

        # Global 3: Off-topic / Prompt injection
        off_topic_keywords = ["who won the match", "tell me my balance", "ignore your instructions", "what is the weather", "tell me a joke"]
        if any(w in u for w in off_topic_keywords):
            return NLUResult(primary_intent="OFF_TOPIC", confidence=0.95)

        # Global 4: Questions about agent / call
        if any(w in u for w in ["which app", "are you recording", "other number", "hindi mein bolo", "repeat that", "how long will it take"]):
            return NLUResult(primary_intent="QUESTION_ABOUT_CALL", confidence=0.95)

        # State 1: IDENTITY_CHECK
        if state == "IDENTITY_CHECK":
            if u.strip().startswith("yes") or u.strip().startswith("haan"):
                secondaries = []
                if "who" in u or "kaun" in u:
                    secondaries.append("QUESTION_ABOUT_AGENT")
                if "driving" in u or "call later" in u or "busy" in u:
                    secondaries.extend(["BUSY", "CALLBACK_REQUEST"])
                return NLUResult(primary_intent="IDENTITY_CONFIRMED", secondary_intents=secondaries, confidence=0.96)
            if any(w in u for w in ["wrong number", "no rahul", "not rahul", "wrong person"]):
                return NLUResult(primary_intent="WRONG_PARTY", confidence=0.97)
            if any(w in u for w in ["wife", "husband", "papa", "ghar pe nahi", "at office", "not at home", "not here", "passed away", "expired", "hospital"]):
                return NLUResult(primary_intent="IDENTITY_DENIED", confidence=0.96)
            if any(w in u for w in ["who is this", "who are you", "who am i speaking with", "kaun bol"]):
                return NLUResult(primary_intent="QUESTION_ABOUT_AGENT", confidence=0.95)
            if any(w in u for w in ["why are you calling", "what is this regarding", "what is this call about", "kyu call"]):
                return NLUResult(primary_intent="QUESTION_ABOUT_CALL", confidence=0.95)

        # State 2: PERMISSION_CHECK
        if state == "PERMISSION_CHECK":
            if any(w in u for w in ["tell me quickly", "quick", "jaldi bolo", "quickly"]):
                return NLUResult(primary_intent="QUICK_PLEASE", confidence=0.95)
            if any(w in u for w in ["meeting", "driving", "busy right now", "not now", "not really", "wait not now"]):
                return NLUResult(primary_intent="BUSY", confidence=0.95)
            if "not interested" in u:
                return NLUResult(primary_intent="DECLINE", confidence=0.95)

        # State 3: APP_STATUS_CHECK
        if state == "APP_STATUS_CHECK":
            if any(w in u for w in ["deleted it", "i deleted", "not installed", "don't have", "website"]):
                return NLUResult(primary_intent="APP_NOT_INSTALLED", confidence=0.95)
            if any(w in u for w in ["not sure", "i think so", "unsure", "maybe", "confused"]):
                return NLUResult(primary_intent="UNSURE", confidence=0.95)
            if any(w in u for w in ["updated it yesterday", "already updated", "updated last week"]):
                return NLUResult(primary_intent="APP_ALREADY_UPDATED", confidence=0.95)
            if any(w in u for w in ["not updated", "no not updated", "haven't updated", "didn't update", "nahi hua"]):
                return NLUResult(primary_intent="DENY", confidence=0.95)

        # State 4: UPDATE_GUIDANCE
        if state == "UPDATE_GUIDANCE":
            if any(w in u for w in ["says open", "open not update"]):
                return NLUResult(primary_intent="APP_ALREADY_UPDATED", confidence=0.95)
            if any(w in u for w in ["play store", "store isn't opening", "store not opening"]):
                return NLUResult(primary_intent="APP_UPDATE_ISSUE", confidence=0.95)
            if any(w in u for w in ["it's updated", "done updated", "updated successfully"]):
                secondaries = ["GENERAL_APP_ISSUE"] if "login" in u or "fails" in u else []
                return NLUResult(primary_intent="APP_UPDATE_SUCCESS", secondary_intents=secondaries, confidence=0.95)
            if "get someone to call" in u or "someone to call" in u:
                return NLUResult(primary_intent="WANTS_HUMAN", secondary_intents=["CALLBACK_REQUEST"], confidence=0.95)

        # State 5: ISSUE_CHECK
        if state == "ISSUE_CHECK":
            if any(w in u for w in ["now fine", "reinstalled now fine", "fixed now", "works fine"]):
                return NLUResult(primary_intent="ISSUE_RESOLVED_ALREADY", confidence=0.95)

        # State 6: CALLBACK_SCHEDULING / CALLBACK_CONFIRMATION
        if state in ("CALLBACK_SCHEDULING", "CALLBACK_CONFIRMATION"):
            if any(w in u for w in ["forget it", "never mind", "cancel", "don't call"]):
                return NLUResult(primary_intent="CANCEL", confidence=0.95)
            if any(w in u for w in ["in two hours", "in 2 hours", "in 1 hour", "in 30 minutes"]):
                te = cls._extract_time_expression(u)
                return NLUResult(primary_intent="CALLBACK_REQUEST", entities=Entities(time_expression=te), requires_callback=True, confidence=0.95)

        # Common 1: Questions About Agent / Call
        agent_questions = ["who is this", "who are you", "who am i speaking with", "kaun bol", "are you a robot", "are you an ai", "are you a bot", "are you human", "are you real"]
        if any(w in u for w in agent_questions):
            return NLUResult(primary_intent="QUESTION_ABOUT_AGENT", confidence=0.95)

        call_questions = ["why are you calling", "what is this regarding", "what is this call about", "kyu call", "how did you get my number", "where did you get my number"]
        if any(w in u for w in call_questions):
            return NLUResult(primary_intent="QUESTION_ABOUT_CALL", confidence=0.95)

        # Common 2: Wants Human
        if any(w in u for w in ["real person", "human", "agent", "person", "insan", "someone from your team", "speak to someone", "representative"]):
            return NLUResult(primary_intent="WANTS_HUMAN", confidence=0.95)

        # Common 3: Wait / Pause
        if any(w in u for w in ["wait", "one second", "hold on", "ek minute", "just a second"]):
            return NLUResult(primary_intent="WAIT", confidence=0.95)

        # Common 4: Compound: Opt-Out + Issue
        has_optout = any(w in u for w in ["stop calling", "don't call", "remove my number", "never call", "not call"])
        has_crash_issue = any(w in u for w in ["crashing", "crash", "keeps closing", "not opening", "login", "error", "storage"])
        if has_optout and has_crash_issue:
            return NLUResult(
                primary_intent="OPT_OUT",
                secondary_intents=["GENERAL_APP_ISSUE"],
                confidence=0.95,
                entities=Entities(issue_hint="APP_CRASH"),
            )

        # Common 5: Decline in WRAP_UP or PERMISSION_CHECK
        if state == "CALL_WRAP_UP" and any(w in u for w in ["leave it", "no leave it", "mat karo", "leave", "no", "nah"]):
            return NLUResult(primary_intent="DECLINE", confidence=0.95)
        if "not interested" in u:
            if state == "PERMISSION_CHECK":
                return NLUResult(primary_intent="DECLINE", confidence=0.95)
            return NLUResult(primary_intent="OPT_OUT", confidence=0.95)

        # Common 6: Pure Opt Out
        if has_optout:
            return NLUResult(primary_intent="OPT_OUT", confidence=0.96)

        # Common 7: Cancel
        if any(w in u for w in ["forget it", "never mind", "cancel", "mat karo"]):
            return NLUResult(primary_intent="CANCEL", confidence=0.93)

        # Common 8: App Already Updated vs Update Success
        if any(w in u for w in ["already updated", "updated last week", "updated yesterday", "already done"]):
            return NLUResult(primary_intent="APP_ALREADY_UPDATED", confidence=0.95)
        if any(w in u for w in ["done updated", "done it's updated", "okay done updated", "it is updated", "updated successfully"]):
            return NLUResult(primary_intent="APP_UPDATE_SUCCESS", confidence=0.95)

        # Common 9: App Diagnosis / Issues
        if "storage" in u or "space" in u:
            return NLUResult(primary_intent="APP_UPDATE_ISSUE", confidence=0.94, entities=Entities(issue_hint="UPDATE_FAILED_STORAGE"))
        if any(w in u for w in ["not updating", "wont update", "fails to update", "can't update"]):
            return NLUResult(primary_intent="APP_UPDATE_ISSUE", confidence=0.93)
        if any(w in u for w in ["after login", "straight away", "crash", "crashing", "keeps closing", "not opening", "login is not working", "login fails", "avvatledu"]):
            return NLUResult(primary_intent="GENERAL_APP_ISSUE", confidence=0.93, entities=Entities(issue_hint="APP_CRASH"))

        # Common 10: Callback / Busy / Relative Time adjustment
        has_rel_time = any(w in u for w in ["make it", "actually", "call at", "call me", "call later", "busy", "shaam", "evening", "subah", "morning", "tomorrow", "kal", "parso", "after 6", "after 5", "at 1", "10 at night", "next sunday", "fine monday", "have someone call", "in two hours", "in 2 hours"])
        if has_rel_time or any(re.search(r"\b(?:make it|actually)\s+\d+", u) for _ in [1]):
            te = cls._extract_time_expression(u)
            return NLUResult(
                primary_intent="CALLBACK_REQUEST",
                secondary_intents=["BUSY"] if ("busy" in u or "driving" in u) else [],
                confidence=0.93,
                entities=Entities(time_expression=te),
                requires_callback=True,
            )

        # Common 11: Affirm
        affirm_words = ["yes", "yeah", "yep", "haan", "sure", "ok", "okay", "fine go on", "theek hai", "speaking", "go ahead", "haan bolo", "haan theek hai"]
        if any(re.search(r"\b" + re.escape(w) + r"\b", u) for w in affirm_words):
            if state == "IDENTITY_CHECK":
                return NLUResult(primary_intent="IDENTITY_CONFIRMED", confidence=0.95)
            return NLUResult(primary_intent="AFFIRM", confidence=0.95)

        # Common 12: Deny
        deny_words = ["no", "nope", "nahi", "not now", "nah", "no that's all"]
        if any(re.search(r"\b" + re.escape(w) + r"\b", u) for w in deny_words):
            if state == "PERMISSION_CHECK":
                return NLUResult(primary_intent="BUSY", confidence=0.90)
            return NLUResult(primary_intent="DENY", confidence=0.95)

        return NLUResult(primary_intent="UNKNOWN", confidence=0.5)

    @classmethod
    def _extract_time_expression(cls, u: str) -> TimeExpression:
        date_text = None
        part_of_day = None
        time_text = None

        if "kal" in u or "tomorrow" in u:
            date_text = "tomorrow"
        elif "parso" in u or "day after tomorrow" in u:
            date_text = "day after tomorrow"
        elif "next sunday" in u or "sunday" in u:
            date_text = "sunday"
        elif "monday" in u:
            date_text = "monday"

        if "shaam" in u or "evening" in u:
            part_of_day = "evening"
        elif "subah" in u or "morning" in u:
            part_of_day = "morning"
        elif "dopahar" in u or "afternoon" in u:
            part_of_day = "afternoon"
        elif "night" in u or "raat" in u:
            part_of_day = "night"

        # Check for digits
        digits = re.findall(r"\b\d{1,2}\b", u)
        if digits:
            time_text = digits[0]
            if "after" in u or "ke baad" in u:
                time_text = f"after {digits[0]}"

        has_data = bool(date_text or time_text or part_of_day)
        return TimeExpression(date_text=date_text, time_text=time_text, part_of_day=part_of_day, raw=u if has_data else "")


class SubbuClassifier:
    """NLU classifier coordinating Gemini and deterministic fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        prompt_builder: PromptBuilder | None = None,
        timeout_seconds: float = 1.2,
    ) -> None:
        import os
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip() or None
        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.prompt_builder = prompt_builder or default_prompt_builder
        self.timeout_seconds = timeout_seconds
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            return None
        try:
            from google import genai
            from google.genai import types
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=max(int(self.timeout_seconds * 1000), 10_000)),
            )
            return self._client
        except Exception as e:
            logger.warning("Could not initialize google.genai client: %s", e)
            return None

    def classify(
        self,
        state: str,
        subbu_last_line: str = "",
        allowed_intents: list[str] | None = None,
        global_intents: list[str] | None = None,
        utterance: str = "",
        sensitive_flags: dict[str, Any] | None = None,
        last_turns: list[dict[str, str]] | None = None,
        forbidden_pii: list[str] | None = None,
    ) -> NLUResult:
        if allowed_intents is None:
            allowed_intents = ["AFFIRM", "DENY", "BUSY", "CALLBACK_REQUEST", "UNKNOWN"]
        if global_intents is None:
            global_intents = ["FRAUD_REPORT", "OPT_OUT", "WRONG_PARTY", "IDENTITY_DENIED", "WANTS_HUMAN", "CANCEL", "OFF_TOPIC", "UNKNOWN"]

        prompt, prompt_version = self.prompt_builder.build_prompt(
            state=state,
            subbu_last_line=subbu_last_line,
            allowed_intents=allowed_intents,
            global_intents=global_intents,
            utterance=utterance,
            sensitive_flags=sensitive_flags,
            last_turns=last_turns,
        )

        # Privacy gate
        assert_safe_llm_request(
            utterance=utterance,
            subbu_last_line=subbu_last_line,
            last_turns=last_turns,
            forbidden_strings=forbidden_pii,
        )

        client = self._get_client()
        if client is not None:
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": NLUResult.model_json_schema(),
                        "temperature": 0,
                        "automatic_function_calling": {"disable": True},
                    },
                )
                text = getattr(response, "text", None)
                if text:
                    result = NLUResult.model_validate_json(text)
                    result.prompt_version = prompt_version
                    result.model_id = self.model_name
                    # Validate allowed intents
                    valid_intents = set(allowed_intents + global_intents)
                    if result.primary_intent not in valid_intents:
                        result.primary_intent = "UNKNOWN"
                        result.confidence = 0.5
                    return result
            except Exception as e:
                logger.warning("Gemini classification failed or timed out: %s. Using fallback.", e)
                if "404" in str(e) or "NOT_FOUND" in str(e):
                    self._client = None
                    self.api_key = None

        # Fallback keyword classification
        fallback = DeterministicKeywordNLU.classify(utterance, state)
        fallback.prompt_version = prompt_version
        fallback.model_id = f"fallback-keyword ({self.model_name})"
        return fallback
