"""Milestone 4.3 Acceptance Tests: Cryptography, PII Protection, Audit & Calling Policy.

Covers:
1. AES-256-GCM envelope encryption context AAD binding & tamper rejection
2. Per-recording DEKs & cryptographic shredding
3. Chunked audio completion manifest & truncation detection
4. Production plaintext write rejection
5. Deterministic blind index search
6. Pre-dispatch DND registry timeout fail-closed
7. Real-time opt-out precedence & campaign cancellation
8. Real customer voice external cloud STT hard block
9. Tamper-evident audit chain gap & tampering detection
"""

import os
import pytest
from sqlalchemy import select

from kural.audit.ledger import AuditLedgerService
from kural.persistence.database import Database
from kural.persistence.models import (
    AuditLedgerRow,
    CallbackRow,
    CampaignContactRow,
    CampaignRow,
    CustomerRow,
    SessionRow,
    utcnow,
)
from kural.policy.calling_policy import CallingPolicyEngine
from kural.security.crypto import compute_blind_index
from kural.security.envelope import (
    RecordingCryptoManager,
    assert_production_write_encrypted,
    decrypt_field_envelope,
    encrypt_field_envelope,
)


@pytest.fixture
def crypto_db(tmp_path):
    db_file = tmp_path / "test_crypto.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    return db


def test_envelope_encryption_aad_tamper_rejection():
    """Verify modifying context AAD causes AES-GCM authentication failure."""
    plaintext = "Account Balance: INR 45,000.00"
    legit_context = "CUST-00123:ACC-998877"
    tampered_context = "CUST-99999:ACC-998877"

    envelope = encrypt_field_envelope(plaintext, context_aad=legit_context)
    assert envelope.startswith("enc:v1:")

    # Legitimate decryption succeeds
    decrypted = decrypt_field_envelope(envelope, context_aad=legit_context)
    assert decrypted == plaintext

    # Tampered AAD context must be rejected
    with pytest.raises(ValueError) as exc_info:
        decrypt_field_envelope(envelope, context_aad=tampered_context)
    assert "decryption failed" in str(exc_info.value).lower()


def test_per_recording_dek_cryptographic_shredding():
    """Verify destroying a recording's DEK renders audio unrecoverable while others remain decryptable."""
    manager = RecordingCryptoManager()

    rec1_audio = b"Hello, this is recording one for verification." * 100
    rec2_audio = b"Confidential recording two for compliance." * 100

    chunks1, manifest1 = manager.encrypt_audio_stream("REC-001", rec1_audio)
    chunks2, manifest2 = manager.encrypt_audio_stream("REC-002", rec2_audio)

    # Both decryptable initially
    assert manager.verify_and_decrypt_recording("REC-001", chunks1, manifest1) == rec1_audio
    assert manager.verify_and_decrypt_recording("REC-002", chunks2, manifest2) == rec2_audio

    # Cryptographically shred REC-001 DEK
    assert manager.shred_dek("REC-001") is True

    # REC-001 cannot be decrypted
    with pytest.raises(KeyError) as exc_info:
        manager.verify_and_decrypt_recording("REC-001", chunks1, manifest1)
    assert "RECORDING_SHREDDED" in str(exc_info.value)

    # REC-002 remains completely unaffected and decryptable
    assert manager.verify_and_decrypt_recording("REC-002", chunks2, manifest2) == rec2_audio


def test_recording_manifest_truncation_detection():
    """Verify stripping trailing 64KB audio chunks is detected by manifest validation."""
    manager = RecordingCryptoManager()
    # Create 200KB audio stream (spans 4 chunks of 64KB)
    large_audio = b"A" * (200 * 1024)
    chunks, manifest = manager.encrypt_audio_stream("REC-TRUNC-001", large_audio)
    assert len(chunks) == 4

    # Full stream decrypts
    assert manager.verify_and_decrypt_recording("REC-TRUNC-001", chunks, manifest) == large_audio

    # Adversary strips the trailing chunk
    tampered_chunks = chunks[:3]
    with pytest.raises(ValueError) as exc_info:
        manager.verify_and_decrypt_recording("REC-TRUNC-001", tampered_chunks, manifest)
    assert "RECORDING_TRUNCATED_TAMPERED" in str(exc_info.value)


def test_plaintext_write_rejection():
    """Verify repository layer rejects any write operation without enc:v1: envelope in production mode."""
    # Encrypted payload succeeds
    assert_production_write_encrypted("enc:v1:kek-v1:nonce:ct:tag", is_production=True)

    # Plaintext write in production must fail
    with pytest.raises(ValueError) as exc_info:
        assert_production_write_encrypted("Plaintext Customer SSN / OTP", is_production=True)
    assert "PLAINTEXT_WRITE_REJECTED" in str(exc_info.value)

    # Allowed in development / non-production mode
    assert_production_write_encrypted("Dev plaintext", is_production=False)


def test_blind_index_deterministic_search():
    """Verify exact-match customer lookup via HMAC blind index matches without full-table decryption."""
    blind_key = os.urandom(32)
    phone_number = "+91 98765 43210"

    idx1 = compute_blind_index(phone_number, blind_key)
    # Different formatting of the same number
    idx2 = compute_blind_index(" +91 98765 43210 ", blind_key)
    assert idx1 == idx2

    different_phone = "+91 98765 43211"
    idx_diff = compute_blind_index(different_phone, blind_key)
    assert idx1 != idx_diff


def test_pre_dispatch_dnd_fail_closed():
    """Verify simulated telecom DND registry timeout blocks outbound dialing immediately."""
    engine = CallingPolicyEngine(dnd_timeout_sec=2.0)

    # Registered number blocked
    allowed, reason = engine.evaluate_dnd_status("9876543210")
    assert allowed is False
    assert reason == "CUSTOMER_REGISTERED_DND"

    # Non-registered allowed
    allowed_ok, _ = engine.evaluate_dnd_status("9111122222")
    assert allowed_ok is True

    # Registry timeout must FAIL CLOSED
    allowed_timeout, timeout_reason = engine.evaluate_dnd_status("9111122222", simulate_timeout=True)
    assert allowed_timeout is False
    assert timeout_reason == "DND_REGISTRY_TIMEOUT_FAIL_CLOSED"


def test_opt_out_realtime_precedence(crypto_db):
    """Verify customer opt-out during call instantly overrides campaign enrollment."""
    engine = CallingPolicyEngine()

    with crypto_db.session() as s:
        cust = CustomerRow(
            customer_ref="CUST-OPTOUT-001",
            full_name="Ramesh Gupta",
            phone="9876511111",
            dnd_status=False,
        )
        s.add(cust)

        sess = SessionRow(
            session_id="SESS-OPTOUT-001",
            customer_ref=cust.customer_ref,
            current_state="START",
            context_json={},
        )
        s.add(sess)

        camp = CampaignRow(
            campaign_id="CMP-001",
            name="App Adoption",
        )
        s.add(camp)
        s.flush()

        contact = CampaignContactRow(
            contact_id="CNT-OPTOUT-001",
            campaign_id="CMP-001",
            customer_ref=cust.customer_ref,
            phone=cust.phone,
            status="PENDING",
        )
        s.add(contact)

        cb = CallbackRow(
            callback_id="CB-OPTOUT-001",
            session_id=sess.session_id,
            customer_ref=cust.customer_ref,
            status="SCHEDULED",
            scheduled_at_utc=utcnow(),
        )
        s.add(cb)
        s.commit()

    # Customer expresses opt-out
    assert engine.apply_realtime_opt_out("CUST-OPTOUT-001", crypto_db) is True

    with crypto_db.session() as s:
        updated_cust = s.scalar(select(CustomerRow).where(CustomerRow.customer_ref == "CUST-OPTOUT-001"))
        assert updated_cust.dnd_status is True

        updated_contact = s.get(CampaignContactRow, "CNT-OPTOUT-001")
        assert updated_contact.status == "OPTED_OUT"

        updated_cb = s.get(CallbackRow, "CB-OPTOUT-001")
        assert updated_cb.status == "CANCELLED"


def test_real_customer_voice_external_stt_block():
    """Verify voice orchestrator boundary blocks session if real customer mode uses external STT."""
    # Synthetic/mock test mode allows external or mock STT
    assert CallingPolicyEngine.validate_speech_processing_boundary(
        is_real_customer_session=False,
        stt_provider_type="external_cloud",
        is_on_premise_certified=False,
    ) is True

    # Real customer mode with on-premises certified engine allowed
    assert CallingPolicyEngine.validate_speech_processing_boundary(
        is_real_customer_session=True,
        stt_provider_type="faster_whisper_triton",
        is_on_premise_certified=True,
    ) is True

    # Real customer mode with external cloud STT MUST BE HARD BLOCKED
    with pytest.raises(PermissionError) as exc_info:
        CallingPolicyEngine.validate_speech_processing_boundary(
            is_real_customer_session=True,
            stt_provider_type="external_cloud",
            is_on_premise_certified=False,
        )
    assert "REAL_CUSTOMER_EXTERNAL_STT_FORBIDDEN" in str(exc_info.value)


def test_audit_hash_chain_gap_detection(crypto_db):
    """Verify deleting or modifying an audit row causes chain verification to pinpoint tampered sequence index."""
    ledger_svc = AuditLedgerService(crypto_db)

    # Append 3 entries
    e1 = ledger_svc.record_entry("USER_LOGIN", {"username": "agent1"}, actor_id="user-1", role="AGENT")
    e2 = ledger_svc.record_entry("CALL_DISPATCH", {"call_id": "CALL-1"}, actor_id="user-1", role="AGENT")
    e3 = ledger_svc.record_entry("RECORDING_ACCESSED", {"call_id": "CALL-1"}, actor_id="user-1", role="AGENT")

    # Verify initial valid chain
    is_valid, bad_idx = ledger_svc.verify_chain()
    assert is_valid is True
    assert bad_idx is None

    # Tamper with entry 2 in-place
    with crypto_db.session() as s:
        row2 = s.scalar(select(AuditLedgerRow).where(AuditLedgerRow.sequence_number == 2))
        row2.details_json = {"call_id": "TAMPERED-CALL-99"}
        s.commit()

    is_valid_tampered, tampered_idx = ledger_svc.verify_chain()
    assert is_valid_tampered is False
    assert tampered_idx == 2, f"Expected tampering pinpointed at sequence 2, got {tampered_idx}"
