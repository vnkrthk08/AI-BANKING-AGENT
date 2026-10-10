"""FastAPI dependencies that authenticate the caller and enforce RBAC permissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from kural.security.rbac import check_permission
from kural.security.token_service import decode_and_verify_access_token


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    branch: str
    agent_id: Optional[str] = None

    @property
    def actor(self) -> str:
        return self.username

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "username": self.username, "role": self.role,
            "branch": self.branch, "agent_id": self.agent_id,
        }


def _database(request: Request):
    db = getattr(request.app.state, "database", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database is not available")
    return db


def principal_from_token(request: Request, token: str) -> Principal:
    db = _database(request)
    from kural.persistence.models import AgentRow, UserRow

    def fetch_user_version(user_id: str) -> Optional[int]:
        with db.session() as s:
            u = s.get(UserRow, user_id)
            return u.token_version if u and u.is_active else None

    payload = decode_and_verify_access_token(
        token=token, verify_revocation=True, fetch_user_version_fn=fetch_user_version,
    )
    with db.session() as s:
        user = s.get(UserRow, payload.get("sub"))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is disabled")
        agent_id = s.scalar(select(AgentRow.agent_id).where(AgentRow.user_id == user.id))
        return Principal(
            user_id=user.id, username=user.username, role=user.role,
            branch=user.branch, agent_id=agent_id,
        )


def get_principal(request: Request, authorization: Optional[str] = Header(None)) -> Principal:
    principal = _resolve_principal(request, authorization)
    request.state.principal = principal
    return principal


def _resolve_principal(request: Request, authorization: Optional[str]) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal_from_token(request, authorization[len("Bearer "):].strip())


def require(permission: str) -> Callable[..., Principal]:
    """Dependency factory: authenticate and require one RBAC permission."""

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        _check(principal.role, permission)
        return principal

    dependency.__name__ = f"require_{permission.replace(':', '_')}"
    return dependency


def _check(role: str, permission: str) -> None:
    check_permission(role, permission)


def authorize_stream(conn, session_id: str, permission: str) -> Principal | None:
    """Authenticate a WebSocket/SSE stream with a single-use ticket bound to ``session_id``."""
    return _resolve_stream_principal(conn, session_id, permission)


def _resolve_stream_principal(conn, session_id: str, permission: str) -> Principal | None:
    from kural.persistence.models import AgentRow, UserRow, WebSocketTicketRow
    from kural.security.rbac import has_permission
    from kural.security.token_service import hash_token
    from kural.services.auth_service import AuthService

    ticket = conn.query_params.get("ticket")
    db = getattr(conn.app.state, "database", None)
    if not ticket or db is None:
        return None
    with db.session() as s:
        row = s.get(WebSocketTicketRow, hash_token(ticket))
        user_id = row.user_id if row else None
    if user_id is None or not AuthService(db).validate_and_burn_websocket_ticket(ticket, session_id):
        return None
    with db.session() as s:
        user = s.get(UserRow, user_id)
        if user is None or not user.is_active or not has_permission(user.role, permission):
            return None
        agent_id = s.scalar(select(AgentRow.agent_id).where(AgentRow.user_id == user.id))
        return Principal(user_id=user.id, username=user.username, role=user.role, branch=user.branch, agent_id=agent_id)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.client.host if request.client else "unknown")[:45]
