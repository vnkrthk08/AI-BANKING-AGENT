"""Security package for KURAL AVA Phase 4 production hardening."""

from kural.security.crypto import (
    compute_blind_index,
    decrypt_aes_gcm,
    derive_key,
    encrypt_aes_gcm,
    hash_password,
    verify_password,
)
from kural.security.rbac import Role, check_pii_access_allowed, check_role_membership
from kural.security.revocation_cache import RevocationCache, revocation_cache
from kural.security.token_service import (
    create_access_token,
    decode_and_verify_access_token,
    decrypt_response_envelope,
    encrypt_response_envelope,
    generate_refresh_token_string,
    generate_websocket_ticket,
    get_refresh_cookie_config,
    hash_token,
)

__all__ = [
    "Role",
    "check_pii_access_allowed",
    "check_role_membership",
    "hash_password",
    "verify_password",
    "encrypt_aes_gcm",
    "decrypt_aes_gcm",
    "derive_key",
    "compute_blind_index",
    "RevocationCache",
    "revocation_cache",
    "create_access_token",
    "decode_and_verify_access_token",
    "generate_refresh_token_string",
    "hash_token",
    "encrypt_response_envelope",
    "decrypt_response_envelope",
    "generate_websocket_ticket",
    "get_refresh_cookie_config",
]
