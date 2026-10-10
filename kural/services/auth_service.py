"""Authentication and Identity Service for Phase 4."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kural.persistence.database import Database
from kural.persistence.models import RefreshTokenRow, UserRow, WebSocketTicketRow, utcnow
from kural.security.crypto import hash_password, verify_password
from kural.security.revocation_cache import revocation_cache
from kural.security.token_service import (
    ACCESS_TOKEN_LIFETIME_SEC,
    ENVELOPE_GRACE_WINDOW_SEC,
    REFRESH_TOKEN_LIFETIME_SEC,
    WS_TICKET_LIFETIME_SEC,
    create_access_token,
    decrypt_response_envelope,
    encrypt_response_envelope,
    generate_refresh_token_string,
    generate_websocket_ticket,
    hash_token,
)

logger = logging.getLogger("kural.services.auth")
_DUMMY_HASH = hash_password("kural-timing-equaliser-not-a-real-password")


class AuthService:
    def __init__(self, database: Database) -> None:
        self.db = database

    def startup_cache_sync(self) -> None:
        """Populate the in-memory revocation cache with all active token versions."""
        def fetch_all() -> Dict[str, int]:
            with self.db.session() as s:
                users = s.scalars(select(UserRow)).all()
                return {u.id: u.token_version for u in users}

        revocation_cache.startup_sync(fetch_all)

    def provision_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: str,
        role: str = "AGENT",
        branch: str = "Mumbai Metro",
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new user with Argon2id hashed password."""
        with self.db.session() as s:
            existing = s.scalar(select(UserRow).where((UserRow.username == username) | (UserRow.email == email)))
            if existing:
                raise HTTPException(status_code=400, detail="Username or email already registered")

            pwd_hash = hash_password(password)
            user = UserRow(
                id=str(uuid4()),
                username=username,
                email=email,
                password_hash=pwd_hash,
                full_name=full_name,
                role=role,
                branch=branch,
                phone=phone,
                token_version=0,
                is_active=True,
            )
            s.add(user)
            s.commit()
            revocation_cache.invalidate_user(user.id, 0)
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "branch": user.branch,
            }

    @staticmethod
    def _public_user(user: UserRow) -> Dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "branch": user.branch,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session() as s:
            user = s.get(UserRow, user_id)
            return self._public_user(user) if user else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self.db.session() as s:
            user = s.scalar(select(UserRow).where(UserRow.username == username))
            return self._public_user(user) if user else None

    def list_users(self) -> list[Dict[str, Any]]:
        with self.db.session() as s:
            return [self._public_user(u) for u in s.scalars(select(UserRow).order_by(UserRow.username)).all()]

    def set_active(self, user_id: str, active: bool) -> Dict[str, Any]:
        with self.db.session() as s:
            user = s.get(UserRow, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            user.is_active = active
            if not active:
                user.token_version += 1
                s.execute(update(RefreshTokenRow).where(RefreshTokenRow.user_id == user_id).values(status="REVOKED"))
            s.commit()
            revocation_cache.invalidate_user(user.id, user.token_version)
            return self._public_user(user)

    def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        """Verify user credentials and return user record."""
        with self.db.session() as s:
            user = s.scalar(select(UserRow).where(UserRow.username == username))
            if not user or not user.is_active:
                # Equalise timing so unknown usernames are not distinguishable from wrong passwords.
                verify_password(password, _DUMMY_HASH)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

            if not verify_password(password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "branch": user.branch,
                "token_version": user.token_version,
            }

    def issue_token_pair(self, user_id: str, client_request_id: Optional[str] = None) -> Tuple[str, str]:
        """Issue an access token and an active refresh token with family tracking."""
        with self.db.session() as s:
            user = s.get(UserRow, user_id)
            if not user or not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not active")

            access_token = create_access_token(
                user_id=user.id,
                username=user.username,
                role=user.role,
                branch=user.branch,
                token_version=user.token_version,
            )

            raw_refresh = generate_refresh_token_string()
            token_h = hash_token(raw_refresh)
            family_id = str(uuid4())
            now = utcnow()
            expires_at = now + timedelta(seconds=REFRESH_TOKEN_LIFETIME_SEC)

            rt_row = RefreshTokenRow(
                id=str(uuid4()),
                user_id=user.id,
                family_id=family_id,
                token_hash=token_h,
                status="ACTIVE",
                request_id=client_request_id,
                expires_at=expires_at,
                created_at=now,
            )
            s.add(rt_row)
            s.commit()
            return access_token, raw_refresh

    def rotate_refresh_token(
        self,
        raw_token: str,
        client_request_id: Optional[str],
    ) -> Tuple[str, str]:
        """Atomic refresh-token rotation with encrypted response envelope protocol.
        
        Handles:
        1. ACTIVE token: rotatate to new token, encrypt envelope for 30s grace window.
        2. REPLACED token within grace window + same client_request_id: return decrypted cached envelope.
        3. Replay attack / mismatched request_id / expired grace window: revoke family, increment user token_version.
        """
        token_h = hash_token(raw_token)
        now = utcnow()

        with self.db.session() as s:
            rt = s.scalar(select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_h))
            if not rt:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

            user = s.get(UserRow, rt.user_id)
            if not user or not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

            # Case 1: ACTIVE token exchange
            if rt.status == "ACTIVE":
                if rt.expires_at < now:
                    rt.status = "REVOKED"
                    s.commit()
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

                new_access_token = create_access_token(
                    user_id=user.id,
                    username=user.username,
                    role=user.role,
                    branch=user.branch,
                    token_version=user.token_version,
                )
                new_raw_refresh = generate_refresh_token_string()
                new_token_h = hash_token(new_raw_refresh)
                new_expires_at = now + timedelta(seconds=REFRESH_TOKEN_LIFETIME_SEC)

                # Encrypt response envelope for legitimate concurrent retries
                envelope_b64, nonce_b64, tag_b64 = encrypt_response_envelope(
                    access_token=new_access_token,
                    refresh_token=new_raw_refresh,
                    family_id=rt.family_id,
                    token_id=rt.id,
                )

                rt.status = "REPLACED"
                rt.replaced_at = now
                rt.replaced_by_hash = new_token_h
                rt.request_id = client_request_id
                rt.response_envelope_enc = envelope_b64
                rt.envelope_nonce = nonce_b64
                rt.envelope_tag = tag_b64
                rt.envelope_expires_at = now + timedelta(seconds=ENVELOPE_GRACE_WINDOW_SEC)

                new_rt_row = RefreshTokenRow(
                    id=str(uuid4()),
                    user_id=user.id,
                    family_id=rt.family_id,
                    token_hash=new_token_h,
                    status="ACTIVE",
                    request_id=client_request_id,
                    expires_at=new_expires_at,
                    created_at=now,
                )
                s.add(new_rt_row)
                s.commit()
                return new_access_token, new_raw_refresh

            # Case 2: REPLACED token within grace window
            if rt.status == "REPLACED" and rt.envelope_expires_at and rt.envelope_expires_at >= now:
                # Must match client request ID for safe concurrent return
                if client_request_id and rt.request_id and client_request_id == rt.request_id:
                    if rt.response_envelope_enc and rt.envelope_nonce and rt.envelope_tag:
                        cached = decrypt_response_envelope(
                            envelope_b64=rt.response_envelope_enc,
                            nonce_b64=rt.envelope_nonce,
                            tag_b64=rt.envelope_tag,
                            family_id=rt.family_id,
                            token_id=rt.id,
                        )
                        return cached["access_token"], cached["refresh_token"]

            # Case 3: Replay attack or mismatched request ID or expired grace window
            logger.warning(
                "SECURITY_ALERT: REFRESH_TOKEN_REPLAY_DETECTED for user %s, family %s",
                user.id,
                rt.family_id,
            )
            # Revoke entire token family
            s.execute(
                update(RefreshTokenRow)
                .where(RefreshTokenRow.family_id == rt.family_id)
                .values(status="REVOKED")
            )
            # Increment user token version to immediately invalidate all access tokens
            user.token_version += 1
            s.commit()

            revocation_cache.invalidate_user(user.id, user.token_version)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Security alert: Refresh token replay detected. All sessions terminated.",
            )

    def logout_token(self, raw_token: str) -> None:
        """Revoke a refresh token on logout."""
        token_h = hash_token(raw_token)
        with self.db.session() as s:
            rt = s.scalar(select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_h))
            if rt:
                rt.status = "REVOKED"
                s.commit()

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all tokens for a user (e.g. password reset or breach containment)."""
        with self.db.session() as s:
            user = s.get(UserRow, user_id)
            if not user:
                return 0
            user.token_version += 1
            new_version = user.token_version
            s.execute(
                update(RefreshTokenRow)
                .where(RefreshTokenRow.user_id == user_id)
                .values(status="REVOKED")
            )
            s.commit()
            revocation_cache.invalidate_user(user_id, new_version)
            return new_version

    def issue_websocket_ticket(self, user_id: str, session_id: str) -> str:
        """Generate a short-lived, single-use ticket for WebSocket voice streaming."""
        raw_ticket = generate_websocket_ticket()
        ticket_h = hash_token(raw_ticket)
        now = utcnow()
        expires_at = now + timedelta(seconds=WS_TICKET_LIFETIME_SEC)

        with self.db.session() as s:
            row = WebSocketTicketRow(
                ticket_hash=ticket_h,
                user_id=user_id,
                session_id=session_id,
                expires_at=expires_at,
                used_at=None,
                created_at=now,
            )
            s.add(row)
            s.commit()

        return raw_ticket

    def validate_and_burn_websocket_ticket(self, raw_ticket: str, session_id: str) -> bool:
        """Validate and single-use burn a WebSocket ticket. Returns True if valid, False otherwise."""
        ticket_h = hash_token(raw_ticket)
        now = utcnow()

        with self.db.session() as s:
            row = s.get(WebSocketTicketRow, ticket_h)
            if not row:
                return False
            if row.used_at is not None:
                # Ticket reuse attempt!
                logger.warning("WebSocket ticket reuse attempt detected: %s", ticket_h[:12])
                return False
            if row.expires_at < now:
                return False
            if row.session_id != session_id:
                return False

            row.used_at = now
            s.commit()
            return True
