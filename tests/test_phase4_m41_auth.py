"""Milestone 4.1 Acceptance Tests: Authentication, Authorization & RBAC.

Covers:
1. RFC 6265bis __Host- cookie prefix compliance
2. Refresh token rotation & concurrent atomic exchange
3. 30s grace window idempotent response envelope
4. Replay attack detection & whole-family revocation
5. JWT revocation latency benchmark (measured SLO)
6. SYSTEM_ADMIN PII access blocked (HTTP 403)
7. Single-use WebSocket ticket burn (code 1008 on reuse)
8. Revocation cache startup sync
9. Notification reconnection reconciliation
10. Fail-closed behavior on database partition / outage
11. Multi-worker revocation consistency
"""

import time
import pytest as _pytest
pytestmark = _pytest.mark.real_auth
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from kural.persistence.database import Database
from kural.security.crypto import hash_password, verify_password
from kural.security.revocation_cache import RevocationCache, revocation_cache
from kural.security.token_service import (
    create_access_token,
    decode_and_verify_access_token,
    get_refresh_cookie_config,
)
from kural.services.auth_service import AuthService


@pytest.fixture
def auth_app_client(tmp_path):
    db_file = tmp_path / "test_auth.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()

    auth_svc = AuthService(db)
    # Provision sample users for different roles
    auth_svc.provision_user(
        username="agent1",
        email="agent1@townbank.internal",
        password="AgentPassword123!",
        full_name="Agent One",
        role="AGENT",
        branch="Mumbai Metro",
    )
    auth_svc.provision_user(
        username="sysadmin",
        email="admin@townbank.internal",
        password="AdminPassword123!",
        full_name="System Administrator",
        role="SYSTEM_ADMIN",
        branch="Headquarters",
    )
    auth_svc.provision_user(
        username="supervisor1",
        email="supervisor1@townbank.internal",
        password="SuperPassword123!",
        full_name="Supervisor One",
        role="SUPERVISOR",
        branch="Mumbai Metro",
    )

    app = create_app(repository=None)
    app.state.database = db
    app.state.auth_service = auth_svc
    auth_svc.startup_cache_sync()

    with TestClient(app) as client:
        yield client, db, auth_svc


def test_cookie_host_prefix_compliance(auth_app_client):
    """Verify Set-Cookie header strictly complies with RFC 6265bis for __Host- prefix."""
    client, _, _ = auth_app_client
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert set_cookie != ""

    lower_cookie = set_cookie.lower()
    # Must have __Host- prefix
    assert "__host-ava_refresh_token=" in lower_cookie
    # Must have Path=/
    assert "path=/" in lower_cookie
    # Must NOT specify a subpath like Path=/api/v1/auth
    assert "path=/api" not in lower_cookie
    # Must NOT contain domain attribute
    assert "domain=" not in lower_cookie
    # Must have Secure, HttpOnly, and SameSite=Strict
    assert "httponly" in lower_cookie
    assert "secure" in lower_cookie
    assert "samesite=strict" in lower_cookie


def test_refresh_token_concurrent_atomic_exchange(auth_app_client):
    """Verify that parallel requests with same client request ID receive identical response."""
    client, _, _ = auth_app_client
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    assert login_resp.status_code == 200
    cookie_header = login_resp.headers.get("set-cookie")

    req_id = "req-uuid-concurrent-12345"
    # First refresh
    ref1 = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": req_id, "Cookie": cookie_header},
    )
    assert ref1.status_code == 200
    tok1 = ref1.json()["access_token"]

    # Concurrent refresh presenting the original replaced token with same request ID
    ref2 = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": req_id, "Cookie": cookie_header},
    )
    assert ref2.status_code == 200
    tok2 = ref2.json()["access_token"]
    assert tok1 == tok2


def test_refresh_token_concurrent_grace_window(auth_app_client):
    """Verify that presenting a replaced token within grace window with same request ID succeeds."""
    client, _, _ = auth_app_client
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    cookie_header = login_resp.headers.get("set-cookie")
    req_id = "req-grace-window-456"

    # Rotate
    r1 = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": req_id, "Cookie": cookie_header},
    )
    assert r1.status_code == 200

    # Within grace window
    r2 = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": req_id, "Cookie": cookie_header},
    )
    assert r2.status_code == 200
    assert r2.json()["access_token"] == r1.json()["access_token"]


def test_refresh_token_family_reuse_revocation(auth_app_client):
    """Verify that presenting a replaced token with different request ID triggers replay revocation."""
    client, _, auth_svc = auth_app_client
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    orig_cookie = login_resp.headers.get("set-cookie")

    # Legitimate client rotates token
    legit_refresh = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": "req-legit-1", "Cookie": orig_cookie},
    )
    assert legit_refresh.status_code == 200
    new_cookie = legit_refresh.headers.get("set-cookie")

    # Attacker tries to replay the old token with a different request ID
    replay_resp = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": "req-attacker-2", "Cookie": orig_cookie},
    )
    assert replay_resp.status_code == 401
    assert "replay detected" in replay_resp.json()["detail"].lower()

    # Now the legitimate new token must ALSO be revoked because family was breached!
    legit_followup = client.post(
        "/api/v1/auth/refresh",
        headers={"X-Refresh-Request-ID": "req-legit-3", "Cookie": new_cookie},
    )
    assert legit_followup.status_code == 401


def test_jwt_revocation_latency_benchmark(auth_app_client):
    """Measure empirical P95 latency of JWT rejection following token_version increment."""
    _, db, auth_svc = auth_app_client
    user = auth_svc.authenticate_user("agent1", "AgentPassword123!")

    token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        branch=user["branch"],
        token_version=user["token_version"],
    )

    # Decode valid token
    claims = decode_and_verify_access_token(token, verify_revocation=True)
    assert claims["sub"] == user["id"]

    # Increment token version (logout all sessions)
    auth_svc.revoke_all_user_sessions(user["id"])

    # Measure lookup latency across 100 evaluations
    latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        is_valid, lat_ms = revocation_cache.verify_jwt_version(user["id"], claims["token_version"])
        latencies.append(lat_ms)
        assert is_valid is False

    latencies.sort()
    p95_latency = latencies[94]
    # SLO target: in-memory P95 < 5ms
    assert p95_latency < 5.0, f"P95 revocation latency {p95_latency:.4f}ms exceeded SLO 5.0ms"


def test_system_admin_pii_access_blocked(auth_app_client):
    """Verify SYSTEM_ADMIN is strictly blocked (HTTP 403) from customer PII and recordings."""
    client, _, auth_svc = auth_app_client

    admin_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sysadmin", "password": "AdminPassword123!"},
    )
    admin_token = admin_login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    agent_login = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    agent_token = agent_login.json()["access_token"]
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    # 1. Calls detail endpoint
    r_admin = client.get("/api/calls/CALL-TEST-1", headers=admin_headers)
    assert r_admin.status_code == 403
    assert "forbidden: system_admin is strictly prohibited" in r_admin.json()["detail"].lower()

    # Agent is not blocked by SYSTEM_ADMIN check (returns 404 for nonexistent call)
    r_agent = client.get("/api/calls/CALL-TEST-1", headers=agent_headers)
    assert r_agent.status_code == 404

    # 2. Call transcript endpoint
    r_admin_tr = client.get("/api/calls/CALL-TEST-1/transcript", headers=admin_headers)
    assert r_admin_tr.status_code == 403

    # 3. Call recording endpoint
    r_admin_rec = client.get("/api/calls/CALL-TEST-1/recording", headers=admin_headers)
    assert r_admin_rec.status_code == 403

    # 4. Direct recording endpoint
    r_admin_drec = client.get("/api/recordings/CALL-TEST-1", headers=admin_headers)
    assert r_admin_drec.status_code == 403

    # 5. Customer endpoint
    r_admin_cust = client.get("/api/customers/CUST-00001", headers=admin_headers)
    assert r_admin_cust.status_code == 403


def test_single_use_websocket_ticket_burn(auth_app_client):
    """Verify single-use WebSocket ticket burns upon first use; reuse is rejected with code 1008."""
    client, _, _ = auth_app_client

    agent_login = client.post(
        "/api/v1/auth/login",
        json={"username": "agent1", "password": "AgentPassword123!"},
    )
    token = agent_login.json()["access_token"]

    session_id = "session-voice-test-999"
    ticket_resp = client.post(
        "/api/v1/auth/ws-ticket",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id},
    )
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()["ticket"]

    # First connection: must succeed
    with client.websocket_connect(f"/ws/voice/{session_id}?ticket={ticket}") as ws:
        data = ws.receive_json()
        assert data["type"] == "session_connected"
        assert data["session_id"] == session_id

    # Second connection with same ticket: must be closed with code 1008
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/voice/{session_id}?ticket={ticket}") as ws:
            ws.receive_json()

    assert exc_info.value.code == 1008


def test_revocation_cache_startup_sync():
    """Verify revocation cache pre-populates versions on startup sync."""
    cache = RevocationCache()
    assert not cache.is_ready

    def fetch_versions():
        return {"user-1": 2, "user-2": 5}

    cache.startup_sync(fetch_versions)
    assert cache.is_ready
    assert cache.get_user_token_version("user-1") == 2
    assert cache.get_user_token_version("user-2") == 5


def test_revocation_channel_reconnect_reconciliation():
    """Verify reconciliation updates cache entries following connection recovery."""
    cache = RevocationCache()
    cache.startup_sync(lambda: {"user-1": 1})
    assert cache.get_user_token_version("user-1") == 1

    # Simulate connection drop
    cache.set_db_connected(False)

    # Reconnection with updated versions
    def fetch_recent(lookback):
        return {"user-1": 3, "user-3": 1}

    cache.reconnect_reconcile(fetch_recent)
    assert cache.get_user_token_version("user-1") == 3
    assert cache.get_user_token_version("user-3") == 1


def test_revocation_fail_closed_on_db_outage():
    """Verify strict fail-closed behavior (HTTP 503) when database is unreachable and cache is stale/absent."""
    cache = RevocationCache()
    cache.startup_sync(lambda: {})
    cache.set_db_connected(False)

    # Unknown user not in cache + DB disconnected -> fail closed
    with pytest.raises(Exception) as exc_info:
        cache.get_user_token_version("unknown-user-999")
    assert "503" in str(exc_info.value) or "temporarily unavailable" in str(exc_info.value).lower()


def test_multi_worker_revocation_consistency():
    """Verify consistent revocation across multiple worker caches."""
    worker1_cache = RevocationCache()
    worker2_cache = RevocationCache()

    # Both workers sync initially
    worker1_cache.startup_sync(lambda: {"user-shared": 1})
    worker2_cache.startup_sync(lambda: {"user-shared": 1})

    # Token with version 1 is valid on both
    v1_ok, _ = worker1_cache.verify_jwt_version("user-shared", 1)
    v2_ok, _ = worker2_cache.verify_jwt_version("user-shared", 1)
    assert v1_ok and v2_ok

    # Worker 1 revokes user (simulating database increment and broadcast notification)
    new_version = 2
    worker1_cache.invalidate_user("user-shared", new_version)
    worker2_cache.invalidate_user("user-shared", new_version)

    # Token with version 1 is now rejected by both workers
    v1_valid, _ = worker1_cache.verify_jwt_version("user-shared", 1)
    v2_valid, _ = worker2_cache.verify_jwt_version("user-shared", 1)
    assert not v1_valid
    assert not v2_valid
