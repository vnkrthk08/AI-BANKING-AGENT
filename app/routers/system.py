"""System health, integration status and operator controls (emergency stop)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from kural.persistence.database import Database
from kural.security.deps import Principal, client_ip, require
from kural.services.campaign_service import SystemSettings

system_router = APIRouter(prefix="/api/system", tags=["system"])


def schema_status(db: Database) -> dict[str, Any]:
    from pathlib import Path
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if db.url in {"sqlite://", "sqlite:///:memory:"}:
        return {"current": "metadata", "head": head, "at_head": True}
    with db.engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return {"current": current, "head": head, "at_head": current == head}


class StopRequest(BaseModel):
    stopped: bool
    reason: str | None = Field(default=None, max_length=300)


@system_router.get("/health")
async def system_health(request: Request, _: Principal = Depends(require("system:read"))) -> dict[str, Any]:
    """Truthful component status. Nothing is reported healthy unless it was checked."""
    from kural.telephony.config import get_telephony_provider

    state = request.app.state
    components: list[dict[str, Any]] = []
    try:
        state.repository.health_check()
        schema = schema_status(state.database)
        components.append({"key": "database", "label": "Database", "status": "HEALTHY" if schema["at_head"] else "DEGRADED",
                           "detail": f"{state.database.engine.dialect.name} · schema {schema['current']} (head {schema['head']})"})
    except Exception as exc:
        components.append({"key": "database", "label": "Database", "status": "DOWN", "detail": type(exc).__name__})

    llm = state.llm_provider
    llm_ok = bool(getattr(llm, "api_key", None)) or llm.__class__.__name__ not in ("UnavailableLLMProvider",) and bool(getattr(llm, "_api_key", None))
    components.append({"key": "llm", "label": f"Language understanding ({llm.provider_name})",
                       "status": "CONFIGURED" if llm_ok else "NOT_CONFIGURED",
                       "detail": f"Model {llm.model_name}" if llm_ok else "No API key: KURAL uses deterministic rule-based intent fallback."})
    for key, label, prov in (("stt", "Speech recognition", state.realtime_stt_provider), ("tts", "Speech synthesis", state.tts_provider)):
        configured = bool(getattr(prov, "api_key", None) or getattr(prov, "_api_key", None) or getattr(prov, "endpoint_url", None))
        components.append({"key": key, "label": f"{label} ({prov.__class__.__name__.replace('Adapter', '')})",
                           "status": "CONFIGURED" if configured else "NOT_CONFIGURED",
                           "detail": "Credentials present (validated on first call)" if configured else "Set SARVAM_API_KEY to enable live voice."})
    tel = get_telephony_provider()
    health = await tel.health_check()
    components.append({"key": "telephony", "label": f"Telephony ({health.provider_name})", "status": health.status.value,
                       "detail": health.last_error or ("Live PSTN provider" if health.is_live and health.provider_name != "sandbox" else
                                                       "SANDBOX simulator — not a real phone network" if health.provider_name == "sandbox" else "")})
    channels = state.notification_service.get_channel_statuses()
    for ch in channels:
        if ch["channel"] in ("email", "sms"):
            components.append({"key": ch["channel"], "label": ch["label"], "status": ch["status"], "detail": ch["description"]})
    runner = getattr(state, "worker_runner", None)
    components.append({"key": "workers", "label": "Background workers",
                       "status": ("RUNNING" if runner else "NOT_RUNNING_IN_API"),
                       "detail": (f"Last ticks: {runner.last_tick}" + (f" · last error {runner.last_error}" if runner.last_error else "")) if runner
                       else "Run `python -m kural.workers` as a separate process."})
    settings = state.settings
    return {
        "environment": settings.app_env,
        "components": components,
        "dialing": SystemSettings(state.database).dialing_state(),
        "autodial_enabled": settings.outbound_autodial_enabled,
        "dial_allowlist_active": bool(settings.dial_allowlist),
        "recording_enabled": settings.call_recording_enabled,
    }


@system_router.post("/dialing")
def set_dialing(req: StopRequest, request: Request, principal: Principal = Depends(require("system:emergency_stop"))) -> dict[str, Any]:
    from fastapi import HTTPException
    from kural.security.rbac import has_permission
    if not req.stopped and not has_permission(principal.role, "system:resume_dialing"):
        raise HTTPException(status_code=403, detail="Your role may stop dialing but not resume it")
    state = SystemSettings(request.app.state.database).set_dialing_stopped(req.stopped, actor=principal.actor, reason=req.reason)
    request.app.state.report_service.record_audit("DIALING_STOPPED" if req.stopped else "DIALING_RESUMED", "SYSTEM",
                                                  "outbound_dialing", role=principal.role, actor=principal.actor,
                                                  detail=req.reason or "", ip=client_ip(request))
    return state
