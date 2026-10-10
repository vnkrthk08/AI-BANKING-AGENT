"""Operations API: customers, campaigns, calls, agents, compliance, audit, reports and overview.

Every route authenticates the caller and enforces a server-side RBAC permission. All data
comes from persisted records; nothing here fabricates or simulates operational state.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from kural.config import get_settings
from kural.persistence.database import Database
from kural.security.deps import Principal, client_ip, require
from kural.services.agent_service import AgentService
from kural.services.call_service import CallService
from kural.services.campaign_service import CampaignService, CampaignStateError, SystemSettings
from kural.services.customer_service import CustomerService
from kural.services.event_bus import event_bus
from kural.services.recording_service import get_recording_path
from kural.services.report_service import ReportService

operations_router = APIRouter(prefix="/api", tags=["operations"])

SLA_POLICIES = [
    {"priority": "URGENT", "firstContactMinutes": 15, "resolutionHours": 1},
    {"priority": "HIGH", "firstContactMinutes": 60, "resolutionHours": 8},
    {"priority": "NORMAL", "firstContactMinutes": 240, "resolutionHours": 24},
    {"priority": "LOW", "firstContactMinutes": 480, "resolutionHours": 72},
]
MAX_CSV_BYTES = 5 * 1024 * 1024


def _get_services(request: Request) -> tuple[CustomerService, CampaignService, CallService, AgentService, ReportService]:
    state = request.app.state
    db: Database = state.database
    for name, cls in (("customer_service", CustomerService), ("campaign_service", CampaignService),
                      ("call_service", CallService), ("agent_service", AgentService),
                      ("report_service", ReportService)):
        if getattr(state, name, None) is None:
            setattr(state, name, cls(db))
    return state.customer_service, state.campaign_service, state.call_service, state.agent_service, state.report_service


def _audit(request: Request, principal: Principal, action: str, resource_type: str, resource_id: str, detail: str = "") -> None:
    _get_services(request)[4].record_audit(action, resource_type, resource_id, role=principal.role,
                                           actor=principal.actor, detail=detail, ip=client_ip(request))


async def _read_csv(request: Request, file: UploadFile | None) -> str:
    raw = (await file.read(MAX_CSV_BYTES + 1)) if file is not None else await request.body()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is larger than 5 MB")
    content = raw.decode("utf-8-sig", errors="replace")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")
    return content


def _mask_customer(c: dict[str, Any]) -> dict[str, Any]:
    """Customer API responses never include the raw phone number."""
    out = {k: v for k, v in c.items() if k != "phone"}
    out["phone"] = c.get("masked_phone")
    return out


# --- 1. Customers -----------------------------------------------------------------------
@operations_router.get("/customers")
def list_customers(
    request: Request,
    search: str | None = Query(None, max_length=80),
    app_status: str | None = None,
    dnd_status: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require("customer:read")),
) -> list[dict[str, Any]]:
    cust_svc = _get_services(request)[0]
    return [_mask_customer(c) for c in cust_svc.list_customers(
        search=search, app_status=app_status, dnd_status=dnd_status, limit=limit, offset=offset)]


@operations_router.post("/customers")
async def create_customer(request: Request, principal: Principal = Depends(require("customer:write"))) -> dict[str, Any]:
    cust_svc = _get_services(request)[0]
    data = await request.json()
    name = (data.get("full_name") or data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="full_name is required")
    try:
        created = cust_svc.create_customer(
            full_name=name[:128],
            phone=data.get("phone", ""),
            customer_ref=data.get("customer_ref"),
            email=data.get("email"),
            preferred_language=data.get("preferred_language") or data.get("language", "English"),
            app_status=data.get("app_status", "NOT_INSTALLED"),
            app_version=data.get("app_version"),
            dnd_status=bool(data.get("dnd_status", False)),
            account_type=data.get("account_type", "SAVINGS"),
            branch=data.get("branch", "Head Office"),
            region=data.get("region", "All India"),
            assigned_agent_id=data.get("assigned_agent_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _audit(request, principal, "CUSTOMER_UPSERTED", "CUSTOMER", created["customer_ref"])
    return _mask_customer(created)


@operations_router.get("/customers/export")
def export_customers(request: Request, principal: Principal = Depends(require("report:export"))) -> Response:
    csv_text = _get_services(request)[0].export_customers_csv()
    _audit(request, principal, "CUSTOMERS_EXPORTED", "CUSTOMER", "*")
    return Response(content=csv_text, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=customers_export.csv"})


@operations_router.get("/customers/{customer_ref}")
def get_customer(customer_ref: str, request: Request, _: Principal = Depends(require("customer:read"))) -> dict[str, Any]:
    c = _get_services(request)[0].get_customer(customer_ref)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return _mask_customer(c)


@operations_router.patch("/customers/{customer_ref}")
async def patch_customer(customer_ref: str, request: Request,
                         principal: Principal = Depends(require("customer:write"))) -> dict[str, Any]:
    cust_svc = _get_services(request)[0]
    data = await request.json()
    try:
        updated = cust_svc.update_customer(customer_ref, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Customer not found")
    _audit(request, principal, "CUSTOMER_UPDATED", "CUSTOMER", customer_ref, ",".join(sorted(data))[:200])
    return _mask_customer(updated)


@operations_router.post("/customers/import")
async def import_customers(request: Request, file: UploadFile | None = None,
                           principal: Principal = Depends(require("customer:write"))) -> dict[str, Any]:
    content = await _read_csv(request, file)
    result = _get_services(request)[0].import_customers_csv(content)
    _audit(request, principal, "CUSTOMERS_IMPORTED", "CUSTOMER", "*", f"result={ {k: v for k, v in result.items() if k != 'errors'} }")
    return result


# --- 2. Campaigns -----------------------------------------------------------------------
def _dialing_state(request: Request) -> SystemSettings:
    if getattr(request.app.state, "system_settings", None) is None:
        request.app.state.system_settings = SystemSettings(request.app.state.database)
    return request.app.state.system_settings


async def _preflight(request: Request, campaign_id: str) -> dict[str, Any]:
    from kural.telephony.config import get_telephony_provider
    provider = get_telephony_provider()
    healthy: bool | None = None
    if provider.is_configured:
        health = await provider.health_check()
        healthy = health.status.value in ("HEALTHY", "CONNECTED")
    return _get_services(request)[1].preflight(
        campaign_id, telephony_configured=provider.is_configured, telephony_healthy=healthy,
        dialing_stopped=_dialing_state(request).is_dialing_stopped(),
    )


@operations_router.get("/campaigns")
def list_campaigns(request: Request, status: str | None = None, region: str | None = None,
                   _: Principal = Depends(require("campaign:read"))) -> list[dict[str, Any]]:
    return _get_services(request)[1].list_campaigns(status=status, region=region)


@operations_router.post("/campaigns")
async def create_campaign(request: Request, principal: Principal = Depends(require("campaign:manage"))) -> dict[str, Any]:
    data = await request.json()
    name = str(data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=422, detail="Campaign name is required")
    requested_status = str(data.get("status", "DRAFT")).upper()
    if requested_status not in ("DRAFT",):
        raise HTTPException(status_code=422, detail="New campaigns start as DRAFT and must be approved before launch")
    created = _get_services(request)[1].create_campaign(
        name=name[:128],
        objective=data.get("objective", "App adoption"),
        script_version=data.get("scriptVersion") or data.get("script_version", "v1.0"),
        segment_size=0,
        max_attempts=int(data.get("maxAttempts") or data.get("max_attempts") or 3),
        retry_gap_hours=int(data.get("retryGapHours") or data.get("retry_gap_hours") or 24),
        languages=data.get("languages") or ["English"],
        region=data.get("region", "All India"),
        status="DRAFT",
        category=data.get("category", "SERVICE"),
        max_concurrent=int(data.get("maxConcurrent") or data.get("max_concurrent") or 2),
        created_by=principal.actor,
    )
    _audit(request, principal, "CAMPAIGN_CREATED", "CAMPAIGN", created["id"])
    return created


@operations_router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request, _: Principal = Depends(require("campaign:read"))) -> dict[str, Any]:
    c = _get_services(request)[1].get_campaign(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c


@operations_router.get("/campaigns/{campaign_id}/contacts")
def list_campaign_contacts(campaign_id: str, request: Request, status: str | None = None,
                           limit: int = Query(200, ge=1, le=1000),
                           _: Principal = Depends(require("campaign:read"))) -> list[dict[str, Any]]:
    from kural.privacy.masking import mask_phone
    rows = _get_services(request)[1].list_contacts(campaign_id, status=status, limit=limit)
    return [{**r, "phone": mask_phone(r.get("phone"))} for r in rows]


@operations_router.patch("/campaigns/{campaign_id}")
async def patch_campaign(campaign_id: str, request: Request,
                         principal: Principal = Depends(require("campaign:manage"))) -> dict[str, Any]:
    data = await request.json()
    if "status" in data:
        raise HTTPException(status_code=422, detail="Use the approve/start/pause/resume/cancel actions to change status")
    try:
        updated = _get_services(request)[1].update_campaign(campaign_id, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")
    _audit(request, principal, "CAMPAIGN_UPDATED", "CAMPAIGN", campaign_id, ",".join(sorted(data))[:200])
    return updated


@operations_router.post("/campaigns/{campaign_id}/approve")
def approve_campaign(campaign_id: str, request: Request,
                     principal: Principal = Depends(require("campaign:approve"))) -> dict[str, Any]:
    try:
        res = _get_services(request)[1].approve_campaign(campaign_id, actor=principal.actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")
    except CampaignStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _audit(request, principal, "CAMPAIGN_APPROVED", "CAMPAIGN", campaign_id)
    return res


@operations_router.get("/campaigns/{campaign_id}/preflight")
async def campaign_preflight(campaign_id: str, request: Request,
                             _: Principal = Depends(require("campaign:read"))) -> dict[str, Any]:
    try:
        return await _preflight(request, campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")


@operations_router.post("/campaigns/{campaign_id}/start")
@operations_router.post("/campaigns/{campaign_id}/resume")
async def start_campaign(campaign_id: str, request: Request,
                         principal: Principal = Depends(require("campaign:execute"))) -> dict[str, Any]:
    try:
        preflight = await _preflight(request, campaign_id)
        res = _get_services(request)[1].launch_campaign(campaign_id, preflight)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")
    except CampaignStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _audit(request, principal, "CAMPAIGN_STARTED", "CAMPAIGN", campaign_id)
    event_bus.publish("campaign_started", {"campaign_id": campaign_id})
    return res


@operations_router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, request: Request,
                   principal: Principal = Depends(require("campaign:execute"))) -> dict[str, Any]:
    camp_svc = _get_services(request)[1]
    current = camp_svc.get_campaign(campaign_id)
    if not current:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if current["status"] != "ACTIVE":
        raise HTTPException(status_code=409, detail=f"Only active campaigns can be paused (status {current['status']})")
    res = camp_svc.pause_campaign(campaign_id)
    _audit(request, principal, "CAMPAIGN_PAUSED", "CAMPAIGN", campaign_id)
    event_bus.publish("campaign_paused", {"campaign_id": campaign_id})
    return res


@operations_router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str, request: Request,
                    principal: Principal = Depends(require("campaign:execute"))) -> dict[str, Any]:
    try:
        res = _get_services(request)[1].cancel_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")
    except CampaignStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _audit(request, principal, "CAMPAIGN_CANCELLED", "CAMPAIGN", campaign_id)
    return res


@operations_router.post("/campaigns/{campaign_id}/contacts/import")
async def import_campaign_contacts(campaign_id: str, request: Request, file: UploadFile | None = None,
                                   principal: Principal = Depends(require("campaign:manage"))) -> dict[str, Any]:
    camp_svc = _get_services(request)[1]
    if camp_svc.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    content = await _read_csv(request, file)
    result = camp_svc.import_contacts_csv(campaign_id, content)
    _audit(request, principal, "CAMPAIGN_CONTACTS_IMPORTED", "CAMPAIGN", campaign_id,
           f"added={result.get('added')} skipped={result.get('skipped')}")
    return result


# --- 3. Calls -----------------------------------------------------------------------------
@operations_router.get("/calls")
def list_calls(
    request: Request,
    campaign_id: str | None = None,
    disposition: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require("call:read")),
) -> list[dict[str, Any]]:
    return _get_services(request)[2].list_calls(campaign_id=campaign_id, disposition=disposition,
                                                status=status, limit=limit, offset=offset)


@operations_router.get("/calls/export")
def export_calls(request: Request, principal: Principal = Depends(require("report:export"))) -> Response:
    csv_text = _get_services(request)[2].export_calls_csv()
    _audit(request, principal, "CALLS_EXPORTED", "CALL", "*")
    return Response(content=csv_text, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=calls_export.csv"})


@operations_router.get("/calls/{call_id}")
def get_call(call_id: str, request: Request, _: Principal = Depends(require("call:read"))) -> dict[str, Any]:
    c = _get_services(request)[2].get_call(call_id)
    if not c:
        raise HTTPException(status_code=404, detail="Call not found")
    return c


@operations_router.get("/calls/{call_id}/transcript")
def get_call_transcript(call_id: str, request: Request,
                        principal: Principal = Depends(require("transcript:read"))) -> list[dict[str, Any]]:
    call_svc = _get_services(request)[2]
    if call_svc.get_call(call_id) is None:
        raise HTTPException(status_code=404, detail="Call not found")
    _audit(request, principal, "TRANSCRIPT_VIEWED", "CALL", call_id)
    return call_svc.get_call_transcript(call_id)


@operations_router.get("/calls/{call_id}/recording")
def get_call_recording(call_id: str, request: Request,
                       principal: Principal = Depends(require("recording:read"))) -> FileResponse:
    call = _get_services(request)[2].get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    rec_path = get_recording_path(call.get("sessionId") or "") if call.get("recordingAvailable") else None
    if not rec_path:
        raise HTTPException(status_code=404, detail="No recording is stored for this call")
    _audit(request, principal, "RECORDING_ACCESSED", "CALL", call_id)
    return FileResponse(path=str(rec_path), media_type="audio/wav", filename=f"{call_id}.wav")


@operations_router.get("/recordings/{recording_id}")
def get_direct_recording(recording_id: str, request: Request,
                         principal: Principal = Depends(require("recording:read"))) -> FileResponse:
    rec_path = get_recording_path(recording_id)
    if not rec_path:
        raise HTTPException(status_code=404, detail="Recording not found")
    _audit(request, principal, "RECORDING_ACCESSED", "RECORDING", recording_id)
    return FileResponse(path=str(rec_path), media_type="audio/wav", filename=f"{recording_id}.wav")


# --- 4. Agents ------------------------------------------------------------------------------
@operations_router.get("/agents")
def list_agents(request: Request, availability: str | None = None, team: str | None = None,
                _: Principal = Depends(require("agent:read"))) -> dict[str, Any]:
    agent_svc = _get_services(request)[3]
    return {
        "agents": agent_svc.list_agents(availability=availability, team=team),
        "workloads": agent_svc.get_agent_workloads(),
        "slaPolicies": SLA_POLICIES,
    }


@operations_router.post("/agents")
async def create_agent(request: Request, principal: Principal = Depends(require("agent:manage"))) -> dict[str, Any]:
    data = await request.json()
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        agent = _get_services(request)[3].create_agent(
            name=name[:128],
            team=data.get("team", "Digital support"),
            languages=data.get("languages") or ["English"],
            skills=data.get("skills") or ["GENERAL_SUPPORT"],
            availability=data.get("availability", "OFFLINE"),
            agent_id=data.get("agent_id") or data.get("id"),
            user_id=data.get("user_id") or data.get("userId"),
            phone=data.get("phone"),
            email=data.get("email"),
            max_open_cases=int(data.get("max_open_cases") or data.get("maxOpenCases") or 12),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _audit(request, principal, "AGENT_CREATED", "AGENT", agent["id"], f"Registered agent {name}")
    event_bus.publish("agent_created", {"agent_id": agent["id"]})
    return agent


@operations_router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, request: Request, principal: Principal = Depends(require("agent:manage"))) -> dict[str, Any]:
    data = await request.json()
    try:
        updated = _get_services(request)[3].update_agent(agent_id, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    _audit(request, principal, "AGENT_UPDATED", "AGENT", agent_id, ",".join(sorted(data))[:200])
    return updated


@operations_router.patch("/agents/{agent_id}/status")
async def patch_agent_status(agent_id: str, request: Request,
                             principal: Principal = Depends(require("agent:read"))) -> dict[str, Any]:
    from kural.security.rbac import has_permission
    # Agents may change only their own availability; supervisors/managers may change anyone's.
    if not has_permission(principal.role, "agent:manage") and principal.agent_id != agent_id:
        raise HTTPException(status_code=403, detail="You can only change your own availability")
    data = await request.json()
    avail = data.get("availability")
    if not avail:
        raise HTTPException(status_code=400, detail="availability is required")
    try:
        updated = _get_services(request)[3].update_agent_availability(agent_id, str(avail))
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _audit(request, principal, "AGENT_STATUS_CHANGED", "AGENT", agent_id, f"Availability set to {avail}")
    event_bus.publish("agent_status_changed", {"agent_id": agent_id, "availability": updated["availability"]})
    return updated


@operations_router.post("/agents/assign")
async def suggest_agent(request: Request, _: Principal = Depends(require("case:assign"))) -> dict[str, Any]:
    data = await request.json()
    best = _get_services(request)[3].find_best_agent(
        preferred_language=data.get("language", "English"), issue_category=data.get("category", "APP_SUPPORT"))
    if not best:
        raise HTTPException(status_code=404, detail="No available agent with matching skills and capacity")
    return {"assigned_agent": best}


# --- 5. Compliance & audit ------------------------------------------------------------------
@operations_router.get("/compliance/summary")
def get_compliance_summary(request: Request, _: Principal = Depends(require("compliance:read"))) -> dict[str, Any]:
    settings = get_settings()
    calls = _get_services(request)[2].list_calls(limit=500)
    consents = []
    for c in calls:
        if not c.get("connected"):
            continue
        started = datetime.fromisoformat(c["startedAt"])
        consents.append({
            "callId": c["id"],
            "customerRef": c["customerRef"],
            "purpose": "Mobile app service call",
            "consented": bool(c.get("consented")),
            "recordedAt": c["startedAt"],
            "channel": c.get("channel", "VOICE"),
            "retentionUntil": (started + timedelta(days=settings.recording_retention_days)).isoformat(),
        })
    return {
        "consents": consents,
        "egressLogs": [],
        "policy": {
            "callingWindow": f"{settings.calling_window_start_hour:02d}:00–{settings.calling_window_end_hour:02d}:00 IST",
            "sundayCalls": False,
            "recordingEnabled": settings.call_recording_enabled,
            "recordingRetentionDays": settings.recording_retention_days,
            "promotionalCalling": "Disabled (fail-closed)",
            "dialAllowlistActive": bool(settings.dial_allowlist),
        },
    }


@operations_router.get("/audit")
def list_operational_audits(request: Request, limit: int = Query(100, ge=1, le=1000),
                            _: Principal = Depends(require("audit:read"))) -> list[dict[str, Any]]:
    return _get_services(request)[4].list_audits(limit=limit)


@operations_router.post("/audit")
async def record_operational_audit(request: Request, principal: Principal = Depends(require("dashboard:view"))) -> dict[str, Any]:
    """Client-reported UI actions. Actor and role come from the verified token, never the request body."""
    data = await request.json()
    return _get_services(request)[4].record_audit(
        action=str(data.get("action", "UI_ACTION"))[:60],
        resource_type=str(data.get("resourceType") or data.get("resource_type", "GENERAL"))[:40],
        resource_id=str(data.get("resourceId") or data.get("resource_id", "UI"))[:64],
        role=principal.role,
        actor=principal.actor,
        detail=str(data.get("detail", ""))[:500],
        ip=client_ip(request),
    )


# --- 6. Reporting ---------------------------------------------------------------------------
@operations_router.get("/reports/kpi-summary")
def get_kpi_summary(request: Request, campaign_id: str | None = None,
                    _: Principal = Depends(require("dashboard:view"))) -> dict[str, Any]:
    return _get_services(request)[4].get_kpi_summary(campaign_id=campaign_id)


@operations_router.get("/reports/overview")
def get_overview(request: Request, _: Principal = Depends(require("dashboard:view"))) -> dict[str, Any]:
    return _get_services(request)[4].get_overview()


@operations_router.get("/reports/schedules")
def get_report_schedules(request: Request, _: Principal = Depends(require("report:export"))) -> list[dict[str, Any]]:
    return _get_services(request)[4].list_schedules()


@operations_router.post("/reports/schedules")
async def save_report_schedule(request: Request, principal: Principal = Depends(require("report:export"))) -> dict[str, Any]:
    data = await request.json()
    saved = _get_services(request)[4].save_schedule(data)
    _audit(request, principal, "REPORT_SCHEDULE_SAVED", "REPORT", saved["id"])
    return saved


# --- 7. Combined snapshot (kept for API compatibility) -------------------------------------
@operations_router.get("/snapshot")
def get_dashboard_snapshot(request: Request, principal: Principal = Depends(require("dashboard:view"))) -> dict[str, Any]:
    from kural.security.rbac import has_permission

    state = request.app.state
    _, camp_svc, call_svc, agent_svc, rep_svc = _get_services(request)
    can = lambda perm: has_permission(principal.role, perm)  # noqa: E731
    return {
        "calls": call_svc.list_calls(limit=200) if can("call:read") else [],
        "campaigns": camp_svc.list_campaigns() if can("campaign:read") else [],
        "callbacks": state.callback_service.list_callbacks() if can("callback:read") else [],
        "escalations": state.case_service.list_cases() if can("case:read") else [],
        "agents": agent_svc.list_agents() if can("agent:read") else [],
        "workloads": agent_svc.get_agent_workloads() if can("agent:read") else [],
        "slaPolicies": SLA_POLICIES,
        "consents": [],
        "auditEvents": rep_svc.list_audits(limit=100) if can("audit:read") else [],
        "egressLogs": [],
    }
