"""One-request-per-modality development smoke test for the Sarvam SDK.

This script deliberately has no retry loop. SDK retries are disabled on both
requests so a run can issue at most one STT request and one TTS request.
"""

from __future__ import annotations

import base64
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sarvamai import SarvamAI


ROOT = Path(__file__).resolve().parents[1]
STT_SENTENCE = "My banking application is not updating."
TTS_SENTENCE = "Hello, I am AVA. I can help you with your banking application."
OUTPUT_FILE = ROOT / "artifacts" / "sarvam_ava_test.wav"


def safe_error(exc: Exception, secret: str) -> str:
    """Return a short diagnostic without credentials or request headers."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    message = getattr(exc, "message", None) or str(exc)
    message = str(message)
    if secret:
        message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)(api[-_ ]?subscription[-_ ]?key|authorization)\s*[:=]\s*[^,\s]+",
        r"\1=[REDACTED]",
        message,
    )
    message = re.sub(r"[\r\n\t]+", " ", message).strip()
    message = message[:500] or "No provider error message was available."
    return f"HTTP {status}: {message}" if status else message


def make_temporary_wav(destination: Path) -> None:
    """Use Windows' built-in speech engine; no audio package or API is needed."""
    if sys.platform != "win32":
        raise RuntimeError("The temporary sample generator requires Windows System.Speech.")
    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SetOutputToWaveFile($env:KURAL_SARVAM_AUDIO_PATH); "
        "$s.Speak('My banking application is not updating.'); "
        "$s.Dispose()"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        env={**os.environ, "KURAL_SARVAM_AUDIO_PATH": str(destination)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        # Do not surface PowerShell output, which may contain machine details.
        raise RuntimeError("Windows System.Speech could not create the temporary WAV sample.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stt-only",
        action="store_true",
        help="Run only STT (useful after TTS has already succeeded once).",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    if not api_key:
        print("STT: BLOCKED (SARVAM_API_KEY is blank; no request sent)")
        print("TTS: BLOCKED (SARVAM_API_KEY is blank; no request sent)")
        return 2

    client = SarvamAI(api_subscription_key=api_key)
    failed = False

    try:
        with tempfile.TemporaryDirectory(prefix="kural-sarvam-") as temporary_dir:
            wav_path = Path(temporary_dir) / "sample.wav"
            make_temporary_wav(wav_path)
            with wav_path.open("rb") as audio_file:
                stt_result = client.speech_to_text.transcribe(
                    file=audio_file,
                    model="saaras:v4",
                    mode="transcribe",
                    request_options={"max_retries": 0},
                )
        transcript = getattr(stt_result, "transcript", None)
        language = getattr(stt_result, "language_code", None)
        if not transcript:
            raise RuntimeError("Sarvam returned no transcript.")
        print("STT: SUCCESS")
        print(f"Transcript: {transcript}")
        print(f"Language: {language or 'not provided'}")
    except Exception as exc:
        failed = True
        print("STT: FAILED")
        print(f"Error: {safe_error(exc, api_key)}")

    if args.stt_only:
        return 1 if failed else 0

    try:
        tts_result: Any = client.text_to_speech.convert(
            text=TTS_SENTENCE,
            model="bulbul:v3",
            language_code="en-IN",
            output_audio_codec="wav",
            request_options={"max_retries": 0},
        )
        audio_chunks = getattr(tts_result, "audios", None)
        if not audio_chunks:
            raise RuntimeError("Sarvam returned no audio payload.")
        decoded = b"".join(base64.b64decode(chunk, validate=True) for chunk in audio_chunks)
        if not decoded:
            raise RuntimeError("Sarvam returned an empty audio payload.")
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_bytes(decoded)
        print("TTS: SUCCESS")
        print(f"Output file: {OUTPUT_FILE}")
    except Exception as exc:
        failed = True
        print("TTS: FAILED")
        print(f"Error: {safe_error(exc, api_key)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
