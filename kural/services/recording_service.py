"""Audio recording management and PII redaction service."""

import io
import os
import re
import wave
from pathlib import Path

STORAGE_ROOT = Path("storage")
RECORDINGS_DIR = STORAGE_ROOT / "recordings"


def ensure_storage_dirs() -> None:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


PHONE_PATTERN = re.compile(r"(\+?91[\s-]?)?([6-9]\d{4})[\s-]?(\d{5})")
CARD_PATTERN = re.compile(r"\b(\d{4}[\s-]?){3}(\d{4})\b")
OTP_PATTERN = re.compile(r"\b\d{6}\b")
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")


def redact_pii(text: str) -> str:
    """Mask sensitive banking data (phones, cards, OTPs, Aadhaar numbers) for operational logs."""
    if not text:
        return ""

    def mask_phone(match: re.Match[str]) -> str:
        last2 = match.group(3)[-2:]
        return f"+91 98XXX XX{last2}"

    def mask_card(match: re.Match[str]) -> str:
        raw = match.group(0).replace("-", "").replace(" ", "")
        return f"XXXX-XXXX-XXXX-{raw[-4:]}"

    def mask_aadhaar(match: re.Match[str]) -> str:
        raw = match.group(0).replace("-", "").replace(" ", "")
        return f"XXXX-XXXX-{raw[-4:]}"

    masked = CARD_PATTERN.sub(mask_card, text)
    masked = AADHAAR_PATTERN.sub(mask_aadhaar, masked)
    masked = PHONE_PATTERN.sub(mask_phone, masked)
    masked = re.sub(r"(?i)\b(otp|code|pin)\s*(?:is|:)?\s*\d{4,6}\b", r"\1 [REDACTED]", masked)
    return masked


def create_synthetic_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generates a valid silent 16-bit mono PCM WAV buffer for simulated call recordings."""
    num_samples = int(duration_sec * sample_rate)
    pcm_data = b"\x00\x00" * num_samples
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


def save_pcm_to_wav(session_id: str, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
    """Persists raw 16-bit mono PCM bytes to standard WAV file."""
    ensure_storage_dirs()
    target_path = RECORDINGS_DIR / f"{session_id}.wav"
    with wave.open(str(target_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return str(target_path)


def ensure_recording_exists(session_id: str, duration_sec: float = 2.0) -> str:
    """Creates a synthetic recording if none exists on disk, returning path."""
    ensure_storage_dirs()
    target_path = RECORDINGS_DIR / f"{session_id}.wav"
    if not target_path.exists():
        wav_bytes = create_synthetic_wav(duration_sec=duration_sec)
        target_path.write_bytes(wav_bytes)
    return str(target_path)


def get_recording_path(session_id: str) -> Path | None:
    path = RECORDINGS_DIR / f"{session_id}.wav"
    return path if path.exists() else None
