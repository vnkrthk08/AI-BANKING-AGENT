"""Envelope encryption, cryptographic shredding, chunked audio manifests,
and production plaintext write guards for Phase 4.
"""

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from kural.security.crypto import decrypt_aes_gcm, encrypt_aes_gcm

DEFAULT_KEK = os.getenv("KURAL_MASTER_KEK", "kural-ava-production-kek-32bytes!").encode("utf-8")[:32]
if len(DEFAULT_KEK) < 32:
    DEFAULT_KEK = DEFAULT_KEK.ljust(32, b"0")


def encrypt_field_envelope(
    plaintext: str,
    context_aad: str,
    key_id: str = "kek-v1",
    kek: bytes = DEFAULT_KEK,
) -> str:
    """Encrypt a sensitive field using AES-256-GCM bound to context AAD.
    
    Produces format: enc:v1:<key_id>:<nonce_b64>:<ciphertext_b64>:<tag_b64>
    """
    pt_bytes = plaintext.encode("utf-8")
    aad_bytes = context_aad.encode("utf-8")
    ct, nonce, tag = encrypt_aes_gcm(pt_bytes, kek, aad_bytes)

    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    ct_b64 = base64.b64encode(ct).decode("ascii")
    tag_b64 = base64.b64encode(tag).decode("ascii")

    return f"enc:v1:{key_id}:{nonce_b64}:{ct_b64}:{tag_b64}"


def decrypt_field_envelope(
    envelope: str,
    context_aad: str,
    kek: bytes = DEFAULT_KEK,
) -> str:
    """Decrypt an envelope-encrypted field with strict AAD authentication tag verification."""
    if not envelope.startswith("enc:v1:"):
        raise ValueError("Invalid envelope format: missing enc:v1: prefix")

    parts = envelope.split(":")
    if len(parts) != 6:
        raise ValueError(f"Malformed envelope parts: expected 6 parts, got {len(parts)}")

    _, _, key_id, nonce_b64, ct_b64, tag_b64 = parts
    nonce = base64.b64decode(nonce_b64)
    ct = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)
    aad_bytes = context_aad.encode("utf-8")

    pt = decrypt_aes_gcm(ct, kek, nonce, tag, aad_bytes)
    return pt.decode("utf-8")


def assert_production_write_encrypted(value: str, is_production: bool = True) -> None:
    """Guard ensuring that plaintext PII cannot be persisted in production mode."""
    if is_production and not value.startswith("enc:v1:"):
        raise ValueError("PLAINTEXT_WRITE_REJECTED: Sensitive PII must be encrypted with enc:v1: in production mode")


class RecordingCryptoManager:
    """Handles chunked audio encryption, per-recording DEKs, cryptographic shredding,
    and authenticated completion manifests to detect audio truncation or tampering.
    """

    CHUNK_SIZE = 64 * 1024  # 64 KB

    def __init__(self) -> None:
        # In-memory DEK storage simulation (in production: AWS KMS / HSM key storage)
        self._dek_store: Dict[str, bytes] = {}

    def generate_recording_dek(self, recording_id: str) -> bytes:
        dek = os.urandom(32)
        self._dek_store[recording_id] = dek
        return dek

    def get_dek(self, recording_id: str) -> Optional[bytes]:
        return self._dek_store.get(recording_id)

    def shred_dek(self, recording_id: str) -> bool:
        """Cryptographically shred a recording's DEK to render its audio permanently unrecoverable."""
        if recording_id in self._dek_store:
            del self._dek_store[recording_id]
            return True
        return False

    def encrypt_audio_stream(
        self,
        recording_id: str,
        audio_bytes: bytes,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Encrypt audio stream in 64KB chunks and produce an authenticated manifest."""
        dek = self.generate_recording_dek(recording_id)
        chunks = []
        chunk_hashes = []

        total_bytes = len(audio_bytes)
        offset = 0
        chunk_index = 0

        while offset < total_bytes:
            chunk_data = audio_bytes[offset : offset + self.CHUNK_SIZE]
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()
            chunk_hashes.append(chunk_hash)

            aad = f"rec:{recording_id}:chunk:{chunk_index}".encode("utf-8")
            ct, nonce, tag = encrypt_aes_gcm(chunk_data, dek, aad)

            chunks.append({
                "chunk_index": chunk_index,
                "ciphertext": ct,
                "nonce": nonce,
                "tag": tag,
                "chunk_hash": chunk_hash,
            })
            offset += len(chunk_data)
            chunk_index += 1

        # Build authenticated completion manifest
        manifest_payload = {
            "recording_id": recording_id,
            "chunk_count": len(chunks),
            "total_bytes": total_bytes,
            "chunk_hashes": chunk_hashes,
        }
        manifest_json = json.dumps(manifest_payload, sort_keys=True)
        manifest_signature = hmac.new(dek, manifest_json.encode("utf-8"), hashlib.sha256).hexdigest()
        manifest = {
            "payload": manifest_payload,
            "signature": manifest_signature,
        }

        return chunks, manifest

    def verify_and_decrypt_recording(
        self,
        recording_id: str,
        chunks: List[Dict[str, Any]],
        manifest: Dict[str, Any],
    ) -> bytes:
        """Verify completion manifest integrity and decrypt chunks.
        
        Detects stripped chunks, truncation, or tampered audio.
        """
        dek = self.get_dek(recording_id)
        if dek is None:
            raise KeyError(f"RECORDING_SHREDDED: DEK for recording {recording_id} has been destroyed.")

        payload = manifest["payload"]
        expected_chunk_count = payload["chunk_count"]
        expected_hashes = payload["chunk_hashes"]

        # 1. Truncation check
        if len(chunks) != expected_chunk_count:
            raise ValueError(
                f"RECORDING_TRUNCATED_TAMPERED: expected {expected_chunk_count} chunks, found {len(chunks)}"
            )

        # 2. Manifest signature check
        manifest_json = json.dumps(payload, sort_keys=True)
        expected_sig = hmac.new(dek, manifest_json.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, manifest["signature"]):
            raise ValueError("RECORDING_TRUNCATED_TAMPERED: manifest signature verification failed")

        # 3. Decrypt chunks sequentially
        decrypted_parts = []
        for i, chunk in enumerate(chunks):
            aad = f"rec:{recording_id}:chunk:{i}".encode("utf-8")
            pt = decrypt_aes_gcm(chunk["ciphertext"], dek, chunk["nonce"], chunk["tag"], aad)
            # Verify plaintext chunk hash matches manifest
            if hashlib.sha256(pt).hexdigest() != expected_hashes[i]:
                raise ValueError(f"RECORDING_TRUNCATED_TAMPERED: chunk {i} hash mismatch")
            decrypted_parts.append(pt)

        return b"".join(decrypted_parts)
