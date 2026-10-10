"""Token Service for JWT access tokens, refresh token rotation, encrypted response envelopes,
and single-use WebSocket tickets.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import HTTPException, status

from kural.security.crypto import (
    compute_blind_index,
    decrypt_aes_gcm,
    derive_key,
    encrypt_aes_gcm,
)
from kural.security.revocation_cache import revocation_cache

load_dotenv()
# Development/test fallback only: production startup refuses to run without KURAL_MASTER_KEY
# (see kural.config.validate_startup).
DEFAULT_MASTER_KEY = os.getenv("KURAL_MASTER_KEY", "kural-ava-production-master-key-32b!!").encode("utf-8")[:32]
if len(DEFAULT_MASTER_KEY) < 32:
    DEFAULT_MASTER_KEY = DEFAULT_MASTER_KEY.ljust(32, b"0")

ACCESS_TOKEN_LIFETIME_SEC = 900  # 15 minutes
REFRESH_TOKEN_LIFETIME_SEC = 86400 * 7  # 7 days
WS_TICKET_LIFETIME_SEC = 30  # 30 seconds
ENVELOPE_GRACE_WINDOW_SEC = 30  # 30 seconds for concurrent tab refreshes


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def create_access_token(
    user_id: str,
    username: str,
    role: str,
    branch: str,
    token_version: int,
    secret_key: bytes = DEFAULT_MASTER_KEY,
    expires_in_sec: int = ACCESS_TOKEN_LIFETIME_SEC,
) -> str:
    """Generate a signed RFC 7519 compliant JWT access token."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "branch": branch,
        "token_version": token_version,
        "iat": now,
        "exp": now + expires_in_sec,
    }
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    signature = hmac.new(secret_key, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{h_b64}.{p_b64}.{sig_b64}"


def decode_and_verify_access_token(
    token: str,
    secret_key: bytes = DEFAULT_MASTER_KEY,
    verify_revocation: bool = True,
    fetch_user_version_fn: Any = None,
) -> Dict[str, Any]:
    """Decode and cryptographically verify a JWT access token.
    
    Checks:
    1. Structure and signature
    2. Expiration (exp)
    3. Revocation status against revocation_cache
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token structure.",
        )
    h_b64, p_b64, sig_b64 = parts
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    expected_sig = hmac.new(secret_key, signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature.",
        )

    try:
        payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token payload.",
        )

    now = int(time.time())
    if payload.get("exp", 0) < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        )

    if verify_revocation:
        user_id = payload.get("sub")
        token_version = payload.get("token_version", 0)
        is_valid, _latency = revocation_cache.verify_jwt_version(
            user_id, token_version, fetch_user_version_fn
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has been revoked.",
            )

    return payload


def generate_refresh_token_string() -> str:
    """Generate a cryptographically secure random refresh token."""
    return f"rt_{secrets.token_hex(32)}"


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of a token string for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def encrypt_response_envelope(
    access_token: str,
    refresh_token: str,
    family_id: str,
    token_id: str,
    master_key: bytes = DEFAULT_MASTER_KEY,
) -> Tuple[str, str, str]:
    """Derive rotation response key (RRK) and encrypt payload for concurrent grace window.
    
    Returns (envelope_b64, nonce_b64, tag_b64).
    """
    context = f"{family_id}:{token_id}".encode("utf-8")
    rrk = derive_key(master_key, context, length=32)
    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token}).encode("utf-8")
    ct, nonce, tag = encrypt_aes_gcm(payload, rrk, context)
    return (
        base64.b64encode(ct).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
        base64.b64encode(tag).decode("ascii"),
    )


def decrypt_response_envelope(
    envelope_b64: str,
    nonce_b64: str,
    tag_b64: str,
    family_id: str,
    token_id: str,
    master_key: bytes = DEFAULT_MASTER_KEY,
) -> Dict[str, str]:
    """Decrypt the cached response payload for a valid concurrent refresh request."""
    context = f"{family_id}:{token_id}".encode("utf-8")
    rrk = derive_key(master_key, context, length=32)
    ct = base64.b64decode(envelope_b64)
    nonce = base64.b64decode(nonce_b64)
    tag = base64.b64decode(tag_b64)
    pt = decrypt_aes_gcm(ct, rrk, nonce, tag, context)
    return json.loads(pt.decode("utf-8"))


def generate_websocket_ticket() -> str:
    """Generate a single-use cryptographically random WebSocket ticket."""
    return f"wst_{secrets.token_hex(32)}"


def get_refresh_cookie_config(token_value: str, expires_in_sec: int = REFRESH_TOKEN_LIFETIME_SEC) -> Dict[str, Any]:
    """Return strict RFC 6265bis compliant cookie parameters for __Host-ava_refresh_token."""
    return {
        "key": "__Host-ava_refresh_token",
        "value": token_value,
        "max_age": expires_in_sec,
        "path": "/",
        "domain": None,
        "secure": True,
        "httponly": True,
        "samesite": "strict",
    }
