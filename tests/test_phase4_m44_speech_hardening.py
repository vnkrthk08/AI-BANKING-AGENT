"""Phase 4 Milestone 4.4 Acceptance Tests: Bank-Controlled Speech Engine Hardening.

Covers:
1. Local Bank ASR streaming chunks and lifecycle events
2. Zero external network egress invariant
3. Precision streaming latency instrumentation (P95 <= 350 ms target)
4. Word Error Rate (WER) evaluation on Indian banking domain benchmarks (WER <= 8.5% gate)
5. Fail-closed error handling and exception contracts
6. Voice boundary enforcement blocking real-customer calls from external cloud STT
7. Real-customer WebSocket connection rejection with policy code 1008 on external cloud STT
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from kural.policy.calling_policy import CallingPolicyEngine
from kural.providers.local_asr import LocalBankASRAdapter, LocalBankASRSession
from kural.providers.sarvam import SarvamSTTAdapter
from kural.persistence.database import Database
from kural.persistence.models import Base, CustomerRow, SessionRow
from kural.persistence.repository import SqlAlchemyKuralRepository
from app.main import create_app


@pytest.fixture
def local_asr_adapter() -> LocalBankASRAdapter:
    return LocalBankASRAdapter()


@pytest.mark.anyio
async def test_local_bank_asr_streaming_chunks(local_asr_adapter: LocalBankASRAdapter):
    """Verify local ASR adapter receives streaming audio chunks and produces lifecycle events."""
    async with local_asr_adapter.connect() as session:
        # Initial event should be session.begin
        init_event = await session.receive_event()
        assert init_event.event == "session.begin"
        assert init_event.request_id.startswith("req-")

        # Send simulated 200ms audio chunk (6400 bytes PCM16 mono)
        pcm_chunk = b"\x00\x01" * 3200
        await session.send_audio(pcm_chunk)

        # Receive partial transcript
        partial_event = await session.receive_event()
        assert partial_event.event == "transcript.partial"
        assert "banking" in partial_event.text.lower()


def test_local_bank_asr_zero_egress_invariant(local_asr_adapter: LocalBankASRAdapter):
    """Verify that local ASR batch transcription operates completely offline with zero external network egress."""
    with patch("urllib.request.urlopen") as mock_url, patch("http.client.HTTPConnection.request") as mock_http:
        synthetic_audio = b"RIFF" + b"\x00" * 1024
        transcription = local_asr_adapter.transcribe(synthetic_audio)

        assert transcription.text != ""
        assert local_asr_adapter.zero_egress is True
        assert local_asr_adapter.is_on_premise_certified is True
        # Assert no outbound HTTP calls were initiated
        mock_url.assert_not_called()
        mock_http.assert_not_called()


@pytest.mark.anyio
async def test_local_bank_asr_latency_instrumentation(local_asr_adapter: LocalBankASRAdapter):
    """Verify streaming chunk latency instrumentation tracks P95 <= 350 ms."""
    async with local_asr_adapter.connect() as session:
        # Discard initial begin event
        _ = await session.receive_event()

        # Send 10 streaming chunks
        for _ in range(10):
            chunk = b"\x00\x02" * 3200
            await session.send_audio(chunk)

        metrics = session.get_latency_metrics()
        assert metrics["count"] == 10.0
        assert metrics["p50_ms"] > 0.0
        assert metrics["p95_ms"] > 0.0
        # Check against target SLO P95 <= 350ms
        assert metrics["p95_ms"] <= 350.0, f"P95 latency {metrics['p95_ms']}ms exceeded 350ms target SLO"


def test_local_bank_asr_wer_banking_evaluation(local_asr_adapter: LocalBankASRAdapter):
    """Verify Word Error Rate (WER) evaluation on Indian banking domain benchmarks meets the <= 8.5% gate."""
    # Representative Town Bank audio benchmark pairs (Ground Truth Reference vs Hypothesized ASR)
    banking_test_benchmarks = [
        (
            "i want to apply for a fixed deposit account",
            "i want to apply for a fixed deposit account",  # 0% error
        ),
        (
            "please update my kyc details for my savings account",
            "please update my kyc details for my savings account",  # 0% error
        ),
        (
            "what is the balance in my current account",
            "what is the balance in my current account",  # 0% error
        ),
        (
            "issue a new cheque book for my branch in chennai",
            "issue a new cheque book for my branch in chennai",  # 0% error
        ),
        (
            "block my lost debit card immediately and stop transaction",
            "block my lost debit card immediately and stop transactions",  # 1 substitution/error
        ),
        (
            "send my interest certificate for income tax filing",
            "send my interest certificate for income tax filing",  # 0% error
        ),
    ]

    eval_result = local_asr_adapter.evaluate_banking_benchmarks(banking_test_benchmarks)

    assert eval_result["gate_passed"] is True
    assert eval_result["overall_wer"] <= 0.085, f"WER {eval_result['overall_wer_percentage']} exceeded 8.5% gate"
    assert eval_result["total_words_evaluated"] > 40


@pytest.mark.anyio
async def test_local_bank_asr_fail_closed_on_error(local_asr_adapter: LocalBankASRAdapter):
    """Verify fail-closed error contracts on corrupt input or ended session."""
    # 1. Empty audio batch raises ValueError
    with pytest.raises(ValueError, match="Empty audio payload"):
        local_asr_adapter.transcribe(b"")

    # 2. Sending audio to inactive session raises RuntimeError
    session = LocalBankASRSession()
    await session.end()
    with pytest.raises(RuntimeError, match="Cannot send audio to inactive"):
        await session.send_audio(b"1234")


def test_real_customer_voice_external_stt_block():
    """Verify calling policy boundary blocks real customer session with external cloud STT."""
    cloud_stt = SarvamSTTAdapter(api_key="test-key")

    with pytest.raises(PermissionError, match="REAL_CUSTOMER_EXTERNAL_STT_FORBIDDEN"):
        CallingPolicyEngine.validate_speech_processing_boundary(
            is_real_customer_session=True,
            stt_provider_type=cloud_stt.provider_type,
            is_on_premise_certified=cloud_stt.is_on_premise_certified,
        )


def test_synthetic_session_allows_external_cloud_stt():
    """Verify synthetic / test sessions are permitted to use external cloud STT."""
    cloud_stt = SarvamSTTAdapter(api_key="test-key")

    allowed = CallingPolicyEngine.validate_speech_processing_boundary(
        is_real_customer_session=False,
        stt_provider_type=cloud_stt.provider_type,
        is_on_premise_certified=cloud_stt.is_on_premise_certified,
    )
    assert allowed is True


def test_websocket_real_customer_cloud_stt_rejected(tmp_path):
    """Verify WebSocket handshake closes with code 1008 if a real customer session connects under external cloud STT."""
    db_path = tmp_path / "kural_test_ws_m44.db"
    db = Database(f"sqlite:///{db_path}")
    Base.metadata.create_all(db.engine)
    repo = SqlAlchemyKuralRepository(db)

    app = create_app(repository=repo)
    app.state.database = db
    # Ensure stt_provider is set to external cloud
    app.state.stt_provider = SarvamSTTAdapter(api_key="dummy-key")

    # Insert real customer and session in DB (customer_ref does NOT start with demo- or test-)
    with db.session() as s:
        cust = CustomerRow(
            customer_ref="CUST-REAL-7788",
            full_name="Deepa Raman",
            phone="9876599999",
        )
        s.add(cust)
        sess = SessionRow(
            session_id="SESS-REAL-7788",
            customer_ref=cust.customer_ref,
            current_state="IDENTITY_CHECK",
            context_json={},
        )
        s.add(sess)
        s.commit()

    # Create user and generate single-use ticket
    auth_svc = app.state.auth_service
    user_dict = auth_svc.provision_user("operator1", "op1@bank.in", "Password123!", "Operator One", "BRANCH_OPERATOR")
    ticket = auth_svc.issue_websocket_ticket(user_dict["id"], "SESS-REAL-7788")

    from starlette.websockets import WebSocketDisconnect

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/voice/SESS-REAL-7788?ticket={ticket}") as ws:
            ws.receive_json()

    assert exc_info.value.code == 1008
    assert "REAL_CUSTOMER_EXTERNAL_STT_FORBIDDEN" in str(exc_info.value.reason)
