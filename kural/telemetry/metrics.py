"""Prometheus metrics exporter and precision turn telemetry (T0 -> T8) for KURAL AVA.

Implements Section 9 precision turn telemetry:
T0: User Speech Start
T1: Silence Detected (VAD End-of-Turn)
T2: STT Transcript Finalized
T3: Intent Extracted & FSM Validated
T4: LLM Generation Started
T5: Policy Check Confirmed
T6: TTS First Audio Chunk Generated (Time to First Audio: T6 - T0)
T7: Audio Played to User
T8: Database Persistence Completed (Full Turn Completion: T8 - T0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Dict, List, Optional


class Histogram:
    """Thread-safe Prometheus histogram."""

    def __init__(self, name: str, help_text: str, buckets: List[float]) -> None:
        self.name = name
        self.help_text = help_text
        self.buckets = sorted(buckets)
        self._lock = threading.Lock()
        self._bucket_counts = [0] * len(self.buckets)
        self._count = 0
        self._sum = 0.0

    def observe(self, val: float) -> None:
        with self._lock:
            self._count += 1
            self._sum += val
            for i, upper in enumerate(self.buckets):
                if val <= upper:
                    self._bucket_counts[i] += 1

    def render(self) -> str:
        with self._lock:
            lines = [
                f"# HELP {self.name} {self.help_text}",
                f"# TYPE {self.name} histogram",
            ]
            cumulative = 0
            for i, upper in enumerate(self.buckets):
                cumulative = self._bucket_counts[i]
                lines.append(f'{self.name}_bucket{{le="{upper:.1f}"}} {cumulative}')
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
            lines.append(f"{self.name}_count {self._count}")
            lines.append(f"{self.name}_sum {self._sum:.2f}")
            return "\n".join(lines)


class Gauge:
    """Thread-safe Prometheus gauge."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._lock = threading.Lock()
        self._value = 0.0

    def set(self, val: float) -> None:
        with self._lock:
            self._value = float(val)

    def inc(self, val: float = 1.0) -> None:
        with self._lock:
            self._value += float(val)

    def dec(self, val: float = 1.0) -> None:
        with self._lock:
            self._value -= float(val)

    def render(self) -> str:
        with self._lock:
            return (
                f"# HELP {self.name} {self.help_text}\n"
                f"# TYPE {self.name} gauge\n"
                f"{self.name} {self._value:.2f}"
            )


class Counter:
    """Thread-safe Prometheus counter."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._lock = threading.Lock()
        self._value = 0.0

    def inc(self, val: float = 1.0) -> None:
        with self._lock:
            self._value += float(val)

    def render(self) -> str:
        with self._lock:
            return (
                f"# HELP {self.name} {self.help_text}\n"
                f"# TYPE {self.name} counter\n"
                f"{self.name} {self._value:.0f}"
            )


class KuralMetricsRegistry:
    """Central metrics collector for KURAL AVA."""

    def __init__(self) -> None:
        self.turn_latency_first_audio_ms = Histogram(
            name="kural_turn_latency_first_audio_ms",
            help_text="Time to First Audio (T6 - T0) in milliseconds",
            buckets=[300.0, 600.0, 900.0, 1200.0, 1500.0, 1800.0, 2500.0],
        )
        self.turn_latency_full_ms = Histogram(
            name="kural_turn_latency_full_ms",
            help_text="Full Turn Completion Latency (T8 - T0) in milliseconds",
            buckets=[500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3500.0],
        )
        self.active_voice_sessions = Gauge(
            name="kural_active_voice_sessions",
            help_text="Current number of active voice sessions",
        )
        self.outbox_lag_seconds = Gauge(
            name="kural_outbox_lag_seconds",
            help_text="Age of oldest unprocessed outbox event in seconds",
        )
        self.dnd_blocks_total = Counter(
            name="kural_dnd_blocks_total",
            help_text="Cumulative count of outbound calls blocked by DND compliance policy",
        )

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format (version 0.0.4)."""
        sections = [
            self.turn_latency_first_audio_ms.render(),
            self.turn_latency_full_ms.render(),
            self.active_voice_sessions.render(),
            self.outbox_lag_seconds.render(),
            self.dnd_blocks_total.render(),
        ]
        return "\n\n".join(sections) + "\n"


# Singleton instance
metrics_registry = KuralMetricsRegistry()


@dataclass
class TurnTelemetryTracker:
    """Tracks precision stages T0 through T8 for an individual conversational turn."""

    session_id: str
    turn_sequence: int
    t0_speech_start: float = field(default_factory=time.perf_counter)
    t1_silence_detected: Optional[float] = None
    t2_stt_finalized: Optional[float] = None
    t3_intent_fsm_validated: Optional[float] = None
    t4_llm_start: Optional[float] = None
    t5_policy_confirmed: Optional[float] = None
    t6_first_audio_chunk: Optional[float] = None
    t7_audio_playback_complete: Optional[float] = None
    t8_turn_persisted: Optional[float] = None

    def mark_t1_silence(self) -> None:
        self.t1_silence_detected = time.perf_counter()

    def mark_t2_stt_final(self) -> None:
        self.t2_stt_finalized = time.perf_counter()

    def mark_t3_intent(self) -> None:
        self.t3_intent_fsm_validated = time.perf_counter()

    def mark_t4_llm_start(self) -> None:
        self.t4_llm_start = time.perf_counter()

    def mark_t5_policy(self) -> None:
        self.t5_policy_confirmed = time.perf_counter()

    def mark_t6_first_audio(self) -> float:
        """Mark Time-to-First-Audio (T6) and record metric."""
        self.t6_first_audio_chunk = time.perf_counter()
        elapsed_ms = (self.t6_first_audio_chunk - self.t0_speech_start) * 1000.0
        metrics_registry.turn_latency_first_audio_ms.observe(elapsed_ms)
        return elapsed_ms

    def mark_t7_audio_playback(self) -> None:
        self.t7_audio_playback_complete = time.perf_counter()

    def mark_t8_persistence(self) -> float:
        """Mark Full Turn Completion (T8) and record metric."""
        self.t8_turn_persisted = time.perf_counter()
        elapsed_ms = (self.t8_turn_persisted - self.t0_speech_start) * 1000.0
        metrics_registry.turn_latency_full_ms.observe(elapsed_ms)
        return elapsed_ms

    def get_summary(self) -> Dict[str, Any]:
        """Calculates stage breakdown in milliseconds."""
        first_audio_ms = (
            (self.t6_first_audio_chunk - self.t0_speech_start) * 1000.0
            if self.t6_first_audio_chunk
            else None
        )
        full_turn_ms = (
            (self.t8_turn_persisted - self.t0_speech_start) * 1000.0
            if self.t8_turn_persisted
            else None
        )
        return {
            "session_id": self.session_id,
            "turn_sequence": self.turn_sequence,
            "user_perceived_latency_ms": round(first_audio_ms, 2) if first_audio_ms else None,
            "full_turn_latency_ms": round(full_turn_ms, 2) if full_turn_ms else None,
        }
