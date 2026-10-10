"""TEST SIMULATOR of an on-premises speech recogniser (returns fixed transcripts).

It performs no recognition and must never serve real calls; the provider factory refuses it
outside APP_ENV=test. Kept for contract tests of the speech-boundary policy.

Original description: local, on-premises bank-controlled speech recognition provider adapter.

Engine: Faster-Whisper (Whisper-large-v3-turbo / medium.en) / NeMo Conformer-CTC on Triton.
Zero Egress: All inference executes strictly within the bank private perimeter.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import logging
import math
import re
import time
from typing import Any, AsyncIterator

from kural.providers.contracts import Transcription

logger = logging.getLogger(__name__)


@dataclass
class LocalASREvent:
    event: str
    text: str = ""
    code: str = ""
    is_fatal: bool = False
    request_id: str = "local-asr-001"
    timestamp: float = field(default_factory=time.perf_counter)


class LocalBankASRSession:
    """Simulates an on-premises streaming ASR session on Triton / Faster-Whisper."""

    def __init__(self, model_name: str = "faster-whisper:large-v3-turbo") -> None:
        self.model_name = model_name
        self._queue: asyncio.Queue[LocalASREvent] = asyncio.Queue()
        self._latencies_ms: list[float] = []
        self._is_active = True
        self._audio_buffer = bytearray()
        # Initial session begin event
        self._queue.put_nowait(LocalASREvent(event="session.begin", request_id=f"req-{int(time.time()*1000)}"))

    async def send_audio(self, pcm16_mono: bytes) -> None:
        """Receive streaming audio chunks (100ms - 250ms), simulate local GPU inference."""
        if not self._is_active:
            raise RuntimeError("Cannot send audio to inactive LocalBankASRSession")

        start = time.perf_counter()
        self._audio_buffer.extend(pcm16_mono)

        # Simulate local Triton GPU inference latency (~30ms - 80ms for 200ms chunk)
        # Latency remains well under the P95 <= 350ms SLO
        inference_latency_ms = 45.0 + (len(pcm16_mono) % 30)
        self._latencies_ms.append(inference_latency_ms)

        # If we have speech buffer, emit partial or final
        if len(self._audio_buffer) >= 6400:  # ~200ms at 16kHz 16-bit mono
            # Simulate transcription extraction
            await self._queue.put(
                LocalASREvent(
                    event="transcript.partial",
                    text="banking query in progress",
                )
            )

    async def receive_event(self) -> LocalASREvent:
        return await self._queue.get()

    async def end(self) -> None:
        self._is_active = False
        await self._queue.put(
            LocalASREvent(
                event="transcript.final",
                text="i want to check my account balance",
            )
        )

    def get_latency_metrics(self) -> dict[str, float]:
        if not self._latencies_ms:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "count": 0.0}
        sorted_latencies = sorted(self._latencies_ms)
        n = len(sorted_latencies)
        p50 = sorted_latencies[int(math.floor(0.50 * (n - 1)))]
        p95 = sorted_latencies[int(math.floor(0.95 * (n - 1)))]
        return {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "max_ms": round(sorted_latencies[-1], 2),
            "count": float(n),
        }


class LocalBankASRAdapter:
    """Bank-controlled on-premises ASR adapter implementing STTProvider and RealtimeSTTProvider."""

    provider_type: str = "on_premise"
    is_on_premise_certified: bool = True
    zero_egress: bool = True
    model_name: str = "faster-whisper:whisper-large-v3-turbo"
    language_code: str = "en-IN"

    def __init__(
        self,
        model_name: str = "faster-whisper:whisper-large-v3-turbo",
        endpoint_url: str = "http://localhost:8001/v2/models/whisper/infer",
    ) -> None:
        self.model_name = model_name
        self.endpoint_url = endpoint_url
        self._inference_latencies: list[float] = []

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "customer.webm",
        content_type: str = "audio/webm",
    ) -> Transcription:
        """Batch / turn transcription within bank perimeter."""
        start = time.perf_counter()
        if not audio:
            raise ValueError("Empty audio payload provided to LocalBankASRAdapter")

        # Simulate local Triton/Faster-Whisper on-premises batch inference
        elapsed_ms = (time.perf_counter() - start) * 1000 + 42.0
        self._inference_latencies.append(elapsed_ms)

        # In production this calls local Triton IPC or localhost REST
        return Transcription(
            text="I want to check my bank account balance and interest rate",
            language_code=self.language_code,
        )

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[LocalBankASRSession]:
        """Establish streaming session with local GPU inference engine."""
        session = LocalBankASRSession(model_name=self.model_name)
        try:
            yield session
        finally:
            await session.end()

    @staticmethod
    def calculate_wer(reference: str, hypothesis: str) -> float:
        """Calculate Word Error Rate (WER) using Levenshtein distance on words."""
        # Normalize punctuation and case
        clean_ref = re.sub(r"[^\w\s]", "", reference.lower()).strip().split()
        clean_hyp = re.sub(r"[^\w\s]", "", hypothesis.lower()).strip().split()

        if not clean_ref:
            return 0.0 if not clean_hyp else 1.0

        r_len = len(clean_ref)
        h_len = len(clean_hyp)
        d = [[0] * (h_len + 1) for _ in range(r_len + 1)]

        for i in range(r_len + 1):
            d[i][0] = i
        for j in range(h_len + 1):
            d[0][j] = j

        for i in range(1, r_len + 1):
            for j in range(1, h_len + 1):
                if clean_ref[i - 1] == clean_hyp[j - 1]:
                    d[i][j] = d[i - 1][j - 1]
                else:
                    substitution = d[i - 1][j - 1] + 1
                    insertion = d[i][j - 1] + 1
                    deletion = d[i - 1][j] + 1
                    d[i][j] = min(substitution, insertion, deletion)

        return round(d[r_len][h_len] / r_len, 4)

    def evaluate_banking_benchmarks(
        self,
        ground_truth_pairs: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Evaluates ground truth pairs against WER <= 8.5% gate."""
        total_ref_words = 0
        total_errors = 0
        pair_results = []

        for ref, hyp in ground_truth_pairs:
            wer = self.calculate_wer(ref, hyp)
            pair_results.append({"ref": ref, "hyp": hyp, "wer": wer})
            clean_ref = re.sub(r"[^\w\s]", "", ref.lower()).strip().split()
            clean_hyp = re.sub(r"[^\w\s]", "", hyp.lower()).strip().split()
            r_len = len(clean_ref)
            total_ref_words += r_len
            total_errors += int(round(wer * r_len))

        overall_wer = round(total_errors / total_ref_words, 4) if total_ref_words > 0 else 0.0
        gate_passed = overall_wer <= 0.085  # <= 8.5%

        return {
            "overall_wer": overall_wer,
            "overall_wer_percentage": f"{overall_wer * 100:.2f}%",
            "gate_passed": gate_passed,
            "threshold": "8.5%",
            "pair_results": pair_results,
            "total_words_evaluated": total_ref_words,
        }
