"""In-memory JWT revocation cache with startup sync, reconnection reconciliation,
bounded TTL (60s), and strict fail-closed behavior on database partition.
"""

import logging
import time
from typing import Callable, Dict, Optional, Tuple

from fastapi import HTTPException, status

logger = logging.getLogger("kural.security.revocation")


class RevocationCache:
    """Multi-worker capable LRU/bounded revocation cache.
    
    Tracks the active `token_version` for users.
    If a JWT's claims contain `token_version < active_token_version`, the JWT is rejected.
    """

    MAX_CACHE_TTL = 60.0  # seconds

    def __init__(self) -> None:
        # user_id -> (token_version, cached_at_timestamp)
        self._cache: Dict[str, Tuple[int, float]] = {}
        self._last_sync_timestamp: float = 0.0
        self._is_ready: bool = False
        self._db_connected: bool = True

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    def set_db_connected(self, connected: bool) -> None:
        """Testing hook to simulate network partitions and database outages."""
        self._db_connected = connected

    def startup_sync(self, fetch_all_active_versions_fn: Callable[[], Dict[str, int]]) -> None:
        """Synchronize all active user token versions from database prior to worker readiness."""
        try:
            versions = fetch_all_active_versions_fn()
            now = time.time()
            for user_id, ver in versions.items():
                self._cache[user_id] = (ver, now)
            self._last_sync_timestamp = now
            self._is_ready = True
            logger.info("Revocation cache startup sync completed: %d users cached.", len(versions))
        except Exception as e:
            self._is_ready = False
            logger.error("Startup sync failed: %s", e)
            raise

    def reconnect_reconcile(self, fetch_recent_versions_fn: Callable[[float], Dict[str, int]]) -> None:
        """Reconcile missed notifications after connection loss using a delta watermark query."""
        try:
            # 10s margin for clock skew and in-flight transactions
            lookback_time = max(0.0, self._last_sync_timestamp - 10.0)
            updated = fetch_recent_versions_fn(lookback_time)
            now = time.time()
            for user_id, ver in updated.items():
                self._cache[user_id] = (ver, now)
            self._last_sync_timestamp = now
            self._db_connected = True
            logger.info("Revocation cache reconnection reconciliation completed: %d users updated.", len(updated))
        except Exception as e:
            logger.error("Reconnection reconciliation failed: %s", e)
            raise

    def invalidate_user(self, user_id: str, new_token_version: int) -> None:
        """Locally invalidate a user's token version upon revocation event."""
        self._cache[user_id] = (new_token_version, time.time())

    def get_user_token_version(
        self,
        user_id: str,
        fetch_user_version_fn: Optional[Callable[[str], Optional[int]]] = None,
    ) -> int:
        """Retrieve user's active token_version with strict fail-closed enforcement.
        
        If entry is absent or expired (> 60s), attempts to refresh from DB.
        If DB is unreachable and cache is stale/absent, FAILS CLOSED (raises 503 or 401).
        """
        now = time.time()
        entry = self._cache.get(user_id)

        # Cache hit and fresh (< MAX_CACHE_TTL)
        if entry is not None and (now - entry[1]) < self.MAX_CACHE_TTL:
            return entry[0]

        # Stale or absent entry: refresh from DB
        if self._db_connected and fetch_user_version_fn is not None:
            try:
                db_version = fetch_user_version_fn(user_id)
                if db_version is not None:
                    self._cache[user_id] = (db_version, now)
                    return db_version
                # User not found in DB
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication failed: user does not exist or has been deleted.",
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("Database lookup failed during token version refresh: %s", e)

        # If we reached here, DB is unreachable or fetch failed
        # STRICT FAIL-CLOSED: if cache is absent or expired, reject the request!
        if entry is None or (now - entry[1]) >= self.MAX_CACHE_TTL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable: unable to verify credential revocation status.",
                headers={"Retry-After": "5"},
            )

        # Fallback to unexpired entry
        return entry[0]

    def verify_jwt_version(
        self,
        user_id: str,
        token_version_in_jwt: int,
        fetch_user_version_fn: Optional[Callable[[str], Optional[int]]] = None,
    ) -> Tuple[bool, float]:
        """Verify whether JWT token_version is active.
        
        Returns (is_valid, lookup_latency_ms).
        """
        t0 = time.perf_counter()
        active_version = self.get_user_token_version(user_id, fetch_user_version_fn)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if token_version_in_jwt < active_version:
            return False, elapsed_ms
        return True, elapsed_ms


# Global singleton instance
revocation_cache = RevocationCache()
