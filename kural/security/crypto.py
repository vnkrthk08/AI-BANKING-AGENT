"""Cryptographic primitives for Phase 4 security and privacy hardening.

Provides:
- Argon2id password hashing and verification using cryptography primitives
- AES-256-GCM envelope encryption with context AAD binding
- HKDF key derivation for ephemeral keys
- HMAC-SHA256 blind indexing for deterministic search
"""

import base64
import hmac
import os
import re
from typing import Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def hash_password(password: str) -> str:
    """Hash a password using Argon2id with 64MB memory, 1 iteration, 4 lanes."""
    salt = os.urandom(16)
    kdf = Argon2id(salt=salt, length=32, iterations=1, lanes=4, memory_cost=65536)
    derived = kdf.derive(password.encode("utf-8"))
    salt_b64 = base64.b64encode(salt).decode("ascii")
    derived_b64 = base64.b64encode(derived).decode("ascii")
    return f"$argon2id$v=19$m=65536,t=1,p=4${salt_b64}${derived_b64}"


def verify_password(password: str, hashed_value: str) -> bool:
    """Verify a password against an Argon2id formatted string."""
    pattern = r"^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$([^$]+)\$([^$]+)$"
    match = re.match(pattern, hashed_value)
    if not match:
        return False
    memory_cost = int(match.group(1))
    iterations = int(match.group(2))
    lanes = int(match.group(3))
    salt = base64.b64decode(match.group(4))
    expected_derived = base64.b64decode(match.group(5))

    kdf = Argon2id(
        salt=salt,
        length=len(expected_derived),
        iterations=iterations,
        lanes=lanes,
        memory_cost=memory_cost,
    )
    try:
        kdf.verify(password.encode("utf-8"), expected_derived)
        return True
    except Exception:
        return False


def encrypt_aes_gcm(
    plaintext: bytes,
    key: bytes,
    associated_data: bytes | None = None,
) -> Tuple[bytes, bytes, bytes]:
    """Encrypt plaintext using AES-256-GCM.
    
    Returns (ciphertext, nonce, tag). Note: cryptography's AESGCM.encrypt appends
    the 16-byte tag to the ciphertext; we split it for explicit storage.
    """
    if len(key) != 32:
        raise ValueError(f"AES-256 requires exactly 32-byte key, got {len(key)}")
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data)
    ciphertext = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return ciphertext, nonce, tag


def decrypt_aes_gcm(
    ciphertext: bytes,
    key: bytes,
    nonce: bytes,
    tag: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    """Decrypt ciphertext using AES-256-GCM with nonce and tag verification."""
    if len(key) != 32:
        raise ValueError(f"AES-256 requires exactly 32-byte key, got {len(key)}")
    aesgcm = AESGCM(key)
    ct_with_tag = ciphertext + tag
    try:
        return aesgcm.decrypt(nonce, ct_with_tag, associated_data)
    except InvalidTag:
        raise ValueError("AES-GCM decryption failed: invalid authentication tag or corrupted data")


def derive_key(master_key: bytes, context: bytes, length: int = 32) -> bytes:
    """Derive an ephemeral sub-key from a master key using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,
        info=context,
    )
    return hkdf.derive(master_key)


def compute_blind_index(plaintext: str, key: bytes) -> str:
    """Compute a deterministic HMAC-SHA256 blind index for exact search."""
    normalized = plaintext.strip().lower().encode("utf-8")
    return hmac.new(key, normalized, hashes.SHA256()).hexdigest()
