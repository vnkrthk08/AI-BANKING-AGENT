"""Environment-based factories for the server-side Sarvam voice adapters."""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from kural.providers.contracts import STTProvider, TTSProvider
from kural.providers.sarvam import SarvamRealtimeSTTAdapter, SarvamSTTAdapter, SarvamTTSAdapter


def _api_key() -> str | None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    return os.getenv("SARVAM_API_KEY")


def create_stt_provider() -> STTProvider:
    provider = os.getenv("STT_PROVIDER", "sarvam").lower()
    if provider in {"local", "on_premise", "bank_hosted"}:
        from kural.providers.local_asr import LocalBankASRAdapter
        return LocalBankASRAdapter()
    return SarvamSTTAdapter(api_key=_api_key())


def create_realtime_stt_provider() -> Any:
    provider = os.getenv("STT_PROVIDER", "sarvam").lower()
    if provider in {"local", "on_premise", "bank_hosted"}:
        from kural.providers.local_asr import LocalBankASRAdapter
        return LocalBankASRAdapter()
    return SarvamRealtimeSTTAdapter(api_key=_api_key())


def create_tts_provider() -> TTSProvider:
    return SarvamTTSAdapter(api_key=_api_key())
