"""Redaction and sensitive data screening for Subbu / Town Bank."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


DIGIT_WORDS = {
    "zero": "0", "oh": "0", "shunya": "0",
    "one": "1", "ek": "1",
    "two": "2", "do": "2",
    "three": "3", "teen": "3",
    "four": "4", "char": "4",
    "five": "5", "paanch": "5", "panch": "5",
    "six": "6", "che": "6", "chhe": "6",
    "seven": "7", "saat": "7",
    "eight": "8", "aath": "8",
    "nine": "9", "nau": "9",
}

# Regex to find double / triple words
RE_DOUBLE_TRIPLE = re.compile(
    r"\b(double|triple)\s+(" + "|".join(DIGIT_WORDS.keys()) + r"|\d)\b",
    re.IGNORECASE,
)


def normalise_spoken_digits(text: str) -> str:
    """Normalise spoken digit words like 'four eight two' or 'double five' into numeric digits."""
    if not text:
        return ""

    # Replace double / triple
    def _expand_multiplier(match: re.Match[str]) -> str:
        multiplier = 2 if match.group(1).lower() == "double" else 3
        word = match.group(2).lower()
        digit = DIGIT_WORDS.get(word, word)
        return digit * multiplier

    working = RE_DOUBLE_TRIPLE.sub(_expand_multiplier, text)

    # Convert individual digit words when in sequence
    tokens = working.split()
    out_tokens: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        clean_token = token.lower().strip(",.-;:!?")
        if clean_token in DIGIT_WORDS:
            out_tokens.append(DIGIT_WORDS[clean_token])
        else:
            out_tokens.append(token)
        i += 1

    result = " ".join(out_tokens)

    # Collapse spaced digits when there are 3 or more separated by spaces,
    # e.g. "4 8 2 9 1 3" -> "482913", while keeping surrounding words
    def _collapse_spaced_digits(match: re.Match[str]) -> str:
        return re.sub(r"\s+", "", match.group(0))

    result = re.sub(r"\b(?:\d\s+){2,}\d\b", _collapse_spaced_digits, result)
    return result


def is_luhn_valid(num_str: str) -> bool:
    """Validate numeric string using Luhn algorithm."""
    digits = [int(c) for c in num_str if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, n in enumerate(reverse_digits):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        checksum += n
    return checksum % 10 == 0


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    sensitive_present: bool
    sensitive_types: list[str] = field(default_factory=list)
    sensitive_count: int = 0
    detected_tokens: list[str] = field(default_factory=list)

    @property
    def masked_text(self) -> str:
        return self.redacted_text

    @property
    def sensitive_flags(self) -> Any:
        class Flags:
            present = self.sensitive_present
            types = self.sensitive_types
            count = self.sensitive_count
        return Flags()


# Context patterns
RE_OTP_CONTEXT = re.compile(
    r"\b(?:otp|one[- ]time password|verification code|security code|code)\b",
    re.IGNORECASE,
)
RE_PIN_CONTEXT = re.compile(
    r"\b(?:pin|mpin|atm pin|upi pin|passcode)\b",
    re.IGNORECASE,
)
RE_CVV_CONTEXT = re.compile(
    r"\b(?:cvv|cvc|security code on card)\b",
    re.IGNORECASE,
)
RE_PASSWORD_CONTEXT = re.compile(
    r"\b(?:password|pwd|netbanking password|login password)\b",
    re.IGNORECASE,
)
RE_ACCOUNT_CONTEXT = re.compile(
    r"\b(?:account|ac|a/c|account number|ac number|account no)\b",
    re.IGNORECASE,
)
RE_CARD_CONTEXT = re.compile(
    r"\b(?:card|card number|debit card|credit card|visa|mastercard|rupay)\b",
    re.IGNORECASE,
)
RE_AADHAAR_CONTEXT = re.compile(
    r"\b(?:aadhaar|aadhar|uidai)\b",
    re.IGNORECASE,
)
RE_PAN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")
RE_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")


def redact_sensitive_data(text: str) -> RedactionResult:
    """
    Screen and redact sensitive financial credentials (OTP, PIN, Password, CVV, Card, Account, Aadhaar, PAN)
    per Spec §8.1.
    Normalises spoken digits first.
    Replaces with [REDACTED_*] tokens before LLM, logs, DB, and dashboard.
    """
    if not text:
        return RedactionResult(redacted_text="", sensitive_present=False)

    normalised = normalise_spoken_digits(text)
    types: list[str] = []
    tokens_found: list[str] = []

    # 1. PAN detection
    def _redact_pan(match: re.Match[str]) -> str:
        types.append("ID")
        tokens_found.append("[REDACTED_ID]")
        return "[REDACTED_ID]"

    res_text = RE_PAN.sub(_redact_pan, normalised)

    # 2. Aadhaar detection (with context or 12 continuous digits with spaces)
    if RE_AADHAAR_CONTEXT.search(res_text):
        def _redact_aadhaar(match: re.Match[str]) -> str:
            types.append("ID")
            tokens_found.append("[REDACTED_ID]")
            return "[REDACTED_ID]"
        res_text = re.sub(r"(?:\b(?:aadhaar|aadhar|uidai)\b[^\d]*)\b(\d{4}[ -]?\d{4}[ -]?\d{4}|\d{12})\b",
                          lambda m: m.group(0).replace(m.group(1), "[REDACTED_ID]"), res_text, flags=re.I)

    # 3. OTP detection: e.g. "otp is 482913", "otp: 1234", "otp 482913", "code is 123456"
    def _redact_otp_phrase(match: re.Match[str]) -> str:
        types.append("OTP")
        tokens_found.append("[REDACTED_OTP]")
        prefix = match.group("prefix")
        return f"{prefix}[REDACTED_OTP]"

    res_text = re.sub(
        r"(?P<prefix>\b(?:otp|one[- ]time password|verification code|security code)\b(?:\s+(?:is|was|it'?s|:|number))?\s*)"
        r"(?P<code>(?:\d[ -]?){4,8})",
        _redact_otp_phrase,
        res_text,
        flags=re.I,
    )

    # Also: "it's 482913" when preceded closely by "otp"
    if RE_OTP_CONTEXT.search(res_text):
        def _redact_otp_nearby(match: re.Match[str]) -> str:
            types.append("OTP")
            tokens_found.append("[REDACTED_OTP]")
            return "[REDACTED_OTP]"
        res_text = re.sub(r"(?<![A-Za-z0-9_\[])\b(?:\d[ -]?){4,8}\b(?![A-Za-z0-9_\]])", _redact_otp_nearby, res_text)

    # 4. PIN detection: e.g. "pin is 1234", "pin 4321", "mpin is 9876", "my pin is 5500"
    def _redact_pin_phrase(match: re.Match[str]) -> str:
        types.append("PIN")
        tokens_found.append("[REDACTED_PIN]")
        prefix = match.group("prefix")
        return f"{prefix}[REDACTED_PIN]"

    res_text = re.sub(
        r"(?P<prefix>\b(?:pin|mpin|atm pin|upi pin|passcode)\b(?:\s+(?:is|was|it'?s|:|number))?\s*)"
        r"(?P<code>(?:\d[ -]?){4,6})",
        _redact_pin_phrase,
        res_text,
        flags=re.I,
    )
    if RE_PIN_CONTEXT.search(res_text):
        def _redact_pin_nearby(match: re.Match[str]) -> str:
            types.append("PIN")
            tokens_found.append("[REDACTED_PIN]")
            return "[REDACTED_PIN]"
        res_text = re.sub(r"(?<![A-Za-z0-9_\[])\b(?:\d[ -]?){4,6}\b(?![A-Za-z0-9_\]])", _redact_pin_nearby, res_text)

    # 5. CVV detection: e.g. "cvv is 123", "cvv 456"
    def _redact_cvv(match: re.Match[str]) -> str:
        types.append("SECRET")
        tokens_found.append("[REDACTED_SECRET]")
        prefix = match.group("prefix")
        return f"{prefix} [REDACTED_SECRET]"

    res_text = re.sub(
        r"(?P<prefix>\b(?:cvv|cvc)\b(?:\s+(?:is|was|it'?s|:|number))?\s*)"
        r"(?P<code>\b\d{3,4}\b)",
        _redact_cvv,
        res_text,
        flags=re.I,
    )

    # 6. Password detection: e.g. "password is hunter2", "password is pass123"
    def _redact_pwd(match: re.Match[str]) -> str:
        types.append("SECRET")
        tokens_found.append("[REDACTED_SECRET]")
        prefix = match.group("prefix")
        return f"{prefix} [REDACTED_SECRET]"

    res_text = re.sub(
        r"(?P<prefix>\b(?:password|pwd|passcode|login password)\b(?:\s+(?:is|was|it'?s|:|to))?\s*)"
        r"(?P<pwd>\b\S+\b)",
        _redact_pwd,
        res_text,
        flags=re.I,
    )

    # 7. Card Number detection (Luhn check or card context)
    def _redact_card(match: re.Match[str]) -> str:
        raw_digits = re.sub(r"\D", "", match.group(0))
        if is_luhn_valid(raw_digits) or RE_CARD_CONTEXT.search(normalised):
            types.append("CARD")
            tokens_found.append("[REDACTED_CARD]")
            return "[REDACTED_CARD]"
        return match.group(0)

    res_text = re.sub(r"\b(?:\d[ -]?){13,19}\b", _redact_card, res_text)

    # 8. Account Number detection (account context + 9-18 digits)
    if RE_ACCOUNT_CONTEXT.search(res_text):
        def _redact_account(match: re.Match[str]) -> str:
            types.append("ACCOUNT")
            tokens_found.append("[REDACTED_ACCOUNT]")
            return "[REDACTED_ACCOUNT]"
        res_text = re.sub(r"(?<![A-Za-z0-9_\[])\b\d{9,18}\b(?![A-Za-z0-9_\]])", _redact_account, res_text)

    # Deduplicate types
    unique_types = sorted(list(set(types)))
    present = len(unique_types) > 0

    return RedactionResult(
        redacted_text=res_text,
        sensitive_present=present,
        sensitive_types=unique_types,
        sensitive_count=len(types),
        detected_tokens=tokens_found,
    )


def detect_sensitive_partial(text: str) -> bool:
    """
    Check if a partial speech transcript contains sensitive markers for barge-in (S-SENS-INTERRUPT).
    """
    if not text:
        return False
    norm = normalise_spoken_digits(text).lower()
    # Check for direct sensitive keywords followed by numbers or indicators
    if re.search(r"\b(?:otp|pin|password|cvv|cvc|card number)\b.*(?:\d|is|it'?s)", norm):
        return True
    if re.search(r"\b(?:my otp is|my pin is|otp is|pin is|password is|cvv is)\b", norm):
        return True
    return False
