"""Authentication API Router for Phase 4."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from kural.security.rbac import Role, check_pii_access_allowed, check_role_membership
from kural.security.token_service import (
    decode_and_verify_access_token,
    get_refresh_cookie_config,
)
from kural.services.auth_service import AuthService

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class WsTicketRequest(BaseModel):
    session_id: str


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
    """Dependency validating JWT access token in Authorization header."""
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

    payload = decode_and_verify_access_token(
        token=token,
        verify_revocation=True,
        fetch_user_version_fn=fetch_user_version,
    )
    return payload


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


@auth_router.post("/login")
def login(
    req: LoginRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    user = auth_svc.authenticate_user(req.username, req.password)
    access_token, refresh_token = auth_svc.issue_token_pair(user["id"])

    cookie_cfg = get_refresh_cookie_config(refresh_token)
    response.set_cookie(
        key=cookie_cfg["key"],
        value=cookie_cfg["value"],
        max_age=cookie_cfg["max_age"],
        path=cookie_cfg["path"],
        domain=cookie_cfg["domain"],
        secure=cookie_cfg["secure"],
        httponly=cookie_cfg["httponly"],
        samesite=cookie_cfg["samesite"],
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@auth_router.post("/refresh")
def refresh(
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
    x_refresh_request_id: Optional[str] = Header(None, alias="X-Refresh-Request-ID"),
    cookie_token: Optional[str] = Cookie(None, alias="__Host-ava_refresh_token"),
) -> Dict[str, Any]:
    if not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing __Host-ava_refresh_token cookie",
        )

    new_access_token, new_refresh_token = auth_svc.rotate_refresh_token(
        raw_token=cookie_token,
        client_request_id=x_refresh_request_id,
    )

    cookie_cfg = get_refresh_cookie_config(new_refresh_token)
    response.set_cookie(
        key=cookie_cfg["key"],
        value=cookie_cfg["value"],
        max_age=cookie_cfg["max_age"],
        path=cookie_cfg["path"],
        domain=cookie_cfg["domain"],
        secure=cookie_cfg["secure"],
        httponly=cookie_cfg["httponly"],
        samesite=cookie_cfg["samesite"],
    )

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
    }


@auth_router.post("/logout")
def logout(
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
    cookie_token: Optional[str] = Cookie(None, alias="__Host-ava_refresh_token"),
) -> Dict[str, str]:
    if cookie_token:
        auth_svc.logout_token(cookie_token)

    # Clear cookie adhering strictly to RFC 6265bis
    response.delete_cookie(
        key="__Host-ava_refresh_token",
        path="/",
        domain=None,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return {"status": "logged_out"}


@auth_router.post("/ws-ticket")
def create_websocket_ticket(
    req: WsTicketRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
) -> Dict[str, Any]:
    ticket = auth_svc.issue_websocket_ticket(current_user["sub"], req.session_id)
    return {
        "ticket": ticket,
        "session_id": req.session_id,
        "expires_in_sec": 30,
    }


@auth_router.get("/me")
def get_me(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return {"user": current_user}
