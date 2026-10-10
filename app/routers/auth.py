"""Authentication, session-token and user-administration API."""

import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from kural.security.deps import Principal, client_ip, get_principal, require
from kural.security.rbac import ALL_ROLES, check_pii_access_allowed, check_role_membership, permissions_for
from kural.security.token_service import decode_and_verify_access_token, get_refresh_cookie_config
from kural.services.auth_service import AuthService

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "__Host-ava_refresh_token"
_LOGIN_WINDOW_SEC = 300
_LOGIN_MAX_FAILURES = 8
_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_failed_lock = threading.Lock()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WsTicketRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    full_name: str = Field(min_length=1, max_length=128)
    role: str
    branch: str = Field(default="Head Office", max_length=80)
    phone: Optional[str] = Field(default=None, max_length=20)


def get_auth_service(request: Request) -> AuthService:
    """Dependency injecting AuthService instance from app state."""
    db = getattr(request.app.state, "database", None)
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return AuthService(db)


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Dependency validating JWT access token in Authorization header (raw claims)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer ") :].strip()

    def fetch_user_version(user_id: str) -> Optional[int]:
        db = getattr(request.app.state, "database", None)
        if not db:
            return None
        from kural.persistence.models import UserRow
        with db.session() as s:
            u = s.get(UserRow, user_id)
            return u.token_version if u else None

    return decode_and_verify_access_token(
        token=token,
        verify_revocation=True,
        fetch_user_version_fn=fetch_user_version,
    )


def require_roles(*roles: str):
    """Dependency factory checking that the authenticated user possesses one of the allowed roles."""
    def dependency(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        check_role_membership(user["role"], set(roles))
        return user
    return dependency


def require_pii_access(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency strictly blocking SYSTEM_ADMIN and unprivileged roles from customer data."""
    check_pii_access_allowed(user["role"])
    return user


def _throttle_key(request: Request, username: str) -> str:
    return f"{client_ip(request)}|{username.lower()}"


def _check_throttle(key: str) -> None:
    now = time.monotonic()
    with _failed_lock:
        attempts = _failed_logins[key]
        while attempts and now - attempts[0] > _LOGIN_WINDOW_SEC:
            attempts.popleft()
        if len(attempts) >= _LOGIN_MAX_FAILURES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed sign-in attempts. Wait a few minutes and try again.",
            )


def _record_failure(key: str) -> None:
    with _failed_lock:
        _failed_logins[key].append(time.monotonic())


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    cfg = get_refresh_cookie_config(refresh_token)
    response.set_cookie(
        key=cfg["key"], value=cfg["value"], max_age=cfg["max_age"], path=cfg["path"],
        domain=cfg["domain"], secure=cfg["secure"], httponly=cfg["httponly"], samesite=cfg["samesite"],
    )


def _audit(request: Request, action: str, actor: str, role: str, resource_id: str, detail: str = "") -> None:
    rep = getattr(request.app.state, "report_service", None)
    if rep is not None:
        rep.record_audit(action, "USER", resource_id, role=role, actor=actor, detail=detail, ip=client_ip(request))


@auth_router.post("/login")
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    key = _throttle_key(request, req.username)
    _check_throttle(key)
    try:
        user = auth_svc.authenticate_user(req.username, req.password)
    except HTTPException:
        _record_failure(key)
        _audit(request, "LOGIN_FAILED", req.username[:60], "ANONYMOUS", req.username[:60])
        raise
    with _failed_lock:
        _failed_logins.pop(key, None)
    access_token, refresh_token = auth_svc.issue_token_pair(user["id"])
    _set_refresh_cookie(response, refresh_token)
    _audit(request, "LOGIN", user["username"], user["role"], user["id"])
    user = {k: v for k, v in user.items() if k != "token_version"}
    user["permissions"] = permissions_for(user["role"])
    return {"access_token": access_token, "token_type": "bearer", "user": user}


@auth_router.post("/refresh")
def refresh(
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
    x_refresh_request_id: Optional[str] = Header(None, alias="X-Refresh-Request-ID"),
    cookie_token: Optional[str] = Cookie(None, alias=REFRESH_COOKIE),
) -> Dict[str, Any]:
    if not cookie_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Missing {REFRESH_COOKIE} cookie")
    new_access_token, new_refresh_token = auth_svc.rotate_refresh_token(
        raw_token=cookie_token, client_request_id=x_refresh_request_id,
    )
    _set_refresh_cookie(response, new_refresh_token)
    return {"access_token": new_access_token, "token_type": "bearer"}


@auth_router.post("/logout")
def logout(
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
    cookie_token: Optional[str] = Cookie(None, alias=REFRESH_COOKIE),
) -> Dict[str, str]:
    if cookie_token:
        auth_svc.logout_token(cookie_token)
    response.delete_cookie(key=REFRESH_COOKIE, path="/", domain=None, secure=True, httponly=True, samesite="strict")
    return {"status": "logged_out"}


@auth_router.post("/ws-ticket")
def create_websocket_ticket(
    req: WsTicketRequest,
    principal: Principal = Depends(get_principal),
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    """Issue a 30-second single-use ticket for a WebSocket/SSE stream bound to one session id."""
    ticket = auth_svc.issue_websocket_ticket(principal.user_id, req.session_id)
    return {"ticket": ticket, "session_id": req.session_id, "expires_in_sec": 30}


@auth_router.get("/me")
def get_me(principal: Principal = Depends(get_principal), auth_svc: AuthService = Depends(get_auth_service)) -> Dict[str, Any]:
    profile = auth_svc.get_user(principal.user_id) or {}
    return {
        "user": {
            **profile,
            "role": principal.role,
            "agent_id": principal.agent_id,
            "permissions": permissions_for(principal.role),
            # Legacy claim names kept for existing API consumers.
            "sub": principal.user_id,
        }
    }


@auth_router.get("/users")
def list_users(_: Principal = Depends(require("user:manage")), auth_svc: AuthService = Depends(get_auth_service)) -> list[Dict[str, Any]]:
    return auth_svc.list_users()


@auth_router.post("/users", status_code=201)
def create_user(
    req: UserCreateRequest,
    request: Request,
    principal: Principal = Depends(require("user:manage")),
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    if req.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail=f"Unknown role. Use one of {sorted(ALL_ROLES)}")
    user = auth_svc.provision_user(
        username=req.username, email=req.email, password=req.password,
        full_name=req.full_name, role=req.role, branch=req.branch, phone=req.phone,
    )
    _audit(request, "USER_CREATED", principal.actor, principal.role, user["id"], f"role={req.role}")
    return user


@auth_router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    principal: Principal = Depends(require("user:manage")),
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    if user_id == principal.user_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    result = auth_svc.set_active(user_id, False)
    _audit(request, "USER_DEACTIVATED", principal.actor, principal.role, user_id)
    return result
