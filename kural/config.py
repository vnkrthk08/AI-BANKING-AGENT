"""Central runtime settings and startup validation.

Every operational component reads configuration through ``get_settings()`` so that
production startup can be validated in one place and fail closed when a critical
secret or dependency is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

INSECURE_DEV_MASTER_KEY = "kural-ava-production-master-key-32b!!"
VALID_ENVS = {"development", "test", "production"}


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def normalize_dial_number(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    master_key_configured: bool
    master_key_is_default: bool
    auto_migrate: bool
    run_workers: bool
    cors_origins: list[str] = field(default_factory=list)
    public_base_url: str = ""
    telephony_provider: str = "disabled"
    telephony_webhook_token: str = ""
    dial_allowlist: frozenset[str] = frozenset()
    outbound_autodial_enabled: bool = False
    call_recording_enabled: bool = False
    recording_retention_days: int = 90
    calling_window_start_hour: int = 9
    calling_window_end_hour: int = 19
    sla_warning_fraction: float = 0.8
    smtp_host: str = ""
    sms_gateway_url: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def is_dial_allowed(self, phone: str) -> bool:
        """An empty allowlist permits any number only in production; elsewhere it blocks all dialing."""
        normalized = normalize_dial_number(phone)
        if self.dial_allowlist:
            return normalized in self.dial_allowlist
        return self.is_production


def load_settings() -> Settings:
    load_dotenv()
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    if app_env not in VALID_ENVS:
        app_env = "development"
    master_key = os.getenv("KURAL_MASTER_KEY", "")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./kural_local.db")
    return Settings(
        app_env=app_env,
        database_url=database_url,
        master_key_configured=bool(master_key),
        master_key_is_default=(not master_key) or master_key == INSECURE_DEV_MASTER_KEY,
        auto_migrate=_bool("KURAL_AUTO_MIGRATE", app_env != "production"),
        run_workers=_bool("KURAL_RUN_WORKERS", app_env == "development"),
        cors_origins=_csv("KURAL_CORS_ORIGINS"),
        public_base_url=os.getenv("KURAL_PUBLIC_BASE_URL", "").rstrip("/"),
        telephony_provider=(os.getenv("TELEPHONY_PROVIDER", "disabled").strip().lower() or "disabled"),
        telephony_webhook_token=os.getenv("TELEPHONY_WEBHOOK_TOKEN", ""),
        dial_allowlist=frozenset(normalize_dial_number(n) for n in _csv("TELEPHONY_DIAL_ALLOWLIST")),
        outbound_autodial_enabled=_bool("KURAL_OUTBOUND_AUTODIAL_ENABLED", False),
        call_recording_enabled=_bool("KURAL_CALL_RECORDING_ENABLED", False),
        recording_retention_days=_int("KURAL_RECORDING_RETENTION_DAYS", 90),
        calling_window_start_hour=_int("KURAL_CALLING_WINDOW_START_HOUR", 9),
        calling_window_end_hour=_int("KURAL_CALLING_WINDOW_END_HOUR", 19),
        smtp_host=os.getenv("SMTP_HOST", ""),
        sms_gateway_url=os.getenv("SMS_GATEWAY_URL", ""),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def validate_startup(settings: Settings) -> list[str]:
    """Return fatal configuration problems. Production refuses to start when any exist."""
    problems: list[str] = []
    if not settings.is_production:
        return problems
    if settings.master_key_is_default:
        problems.append("KURAL_MASTER_KEY must be set to a unique secret of at least 32 characters in production.")
    elif len(os.getenv("KURAL_MASTER_KEY", "")) < 32:
        problems.append("KURAL_MASTER_KEY must be at least 32 characters.")
    if settings.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must point to PostgreSQL in production (SQLite is for local development and tests).")
    if settings.telephony_provider == "sandbox":
        problems.append("TELEPHONY_PROVIDER=sandbox is a simulator and is not permitted in production.")
    if settings.telephony_provider == "exotel" and not settings.telephony_webhook_token:
        problems.append("TELEPHONY_WEBHOOK_TOKEN is required so provider webhooks can be authenticated.")
    if settings.telephony_provider == "exotel" and not settings.public_base_url.startswith("https://"):
        problems.append("KURAL_PUBLIC_BASE_URL must be an https:// URL for telephony status callbacks.")
    if os.getenv("STT_PROVIDER", "").lower() in {"simulated", "local_simulated"}:
        problems.append("The simulated speech recogniser is test-only and cannot run in production.")
    return problems
