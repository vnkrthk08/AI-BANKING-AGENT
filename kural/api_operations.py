"""FastAPI operational endpoints for Phase 3 Bank Operations & Automation."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, Response

from kural.persistence.database import Database
from kural.services.agent_service import AgentService
from kural.services.call_service import CallService
from kural.services.campaign_service import CampaignService
from kural.services.customer_service import CustomerService
from kural.services.event_bus import event_bus
from kural.services.recording_service import ensure_recording_exists, get_recording_path
from kural.services.report_service import ReportService

operations_router = APIRouter(prefix="/api", tags=["operations"])

SLA_POLICIES = [
    {"priority": "URGENT", "firstContactMinutes": 15, "resolutionHours": 4},
    {"priority": "HIGH", "firstContactMinutes": 60, "resolutionHours": 8},
    {"priority": "NORMAL", "firstContactMinutes": 240, "resolutionHours": 24},
    {"priority": "LOW", "firstContactMinutes": 480, "resolutionHours": 48},
]


def _get_services(request: Request) -> tuple[CustomerService, CampaignService, CallService, AgentService, ReportService]:
    app = request.app
    db: Database = getattr(app.state, "database", None)
    if db is None:
        db = Database()
        app.state.database = db

    cust_svc = getattr(app.state, "customer_service", None)
    if cust_svc is None:
        cust_svc = CustomerService(db)
        app.state.customer_service = cust_svc

    camp_svc = getattr(app.state, "campaign_service", None)
    if camp_svc is None:
        camp_svc = CampaignService(db)
        app.state.campaign_service = camp_svc

    call_svc = getattr(app.state, "call_service", None)
    if call_svc is None:
        call_svc = CallService(db)
        app.state.call_service = call_svc

    agent_svc = getattr(app.state, "agent_service", None)
    if agent_svc is None:
        agent_svc = AgentService(db)
        app.state.agent_service = agent_svc

    rep_svc = getattr(app.state, "report_service", None)
    if rep_svc is None:
        rep_svc = ReportService(db)
        app.state.report_service = rep_svc

    return cust_svc, camp_svc, call_svc, agent_svc, rep_svc


def _check_caller_pii_permission(request: Request) -> None:
    role_header = request.headers.get("X-Role")
    if role_header == "SYSTEM_ADMIN":
        from kural.security.rbac import check_pii_access_allowed
        check_pii_access_allowed("SYSTEM_ADMIN")

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer ") :].strip()
        from kural.security.rbac import check_pii_access_allowed
        from kural.security.token_service import decode_and_verify_access_token
        try:
            payload = decode_and_verify_access_token(token, verify_revocation=False)
            role = payload.get("role", "")
            check_pii_access_allowed(role)
        except HTTPException:
            raise
        except Exception:
            pass


# --- 1. Customer Endpoints ---
@operations_router.get("/customers")
def list_customers(
    request: Request,
    search: str | None = None,
    app_status: str | None = None,
    dnd_status: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    cust_svc, _, _, _, _ = _get_services(request)
    return cust_svc.list_customers(search=search, app_status=app_status, dnd_status=dnd_status, limit=limit, offset=offset)


@operations_router.post("/customers")
async def create_customer(request: Request) -> dict[str, Any]:
    cust_svc, _, _, _, _ = _get_services(request)
    data = await request.json()
    try:
        return cust_svc.create_customer(
            full_name=data.get("full_name") or data.get("name", "Unknown"),
            phone=data.get("phone", ""),
            customer_ref=data.get("customer_ref"),
            email=data.get("email"),
            preferred_language=data.get("preferred_language") or data.get("language", "Hindi"),
            app_status=data.get("app_status", "NOT_INSTALLED"),
            app_version=data.get("app_version"),
            dnd_status=bool(data.get("dnd_status", False)),
            account_type=data.get("account_type", "SAVINGS"),
            branch=data.get("branch", "Mumbai Metro"),
            region=data.get("region", "West"),
            assigned_agent_id=data.get("assigned_agent_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@operations_router.get("/customers/export")
def export_customers(request: Request) -> Response:
    cust_svc, _, _, _, _ = _get_services(request)
    csv_text = cust_svc.export_customers_csv()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers_export.csv"},
    )


@operations_router.get("/customers/{customer_ref}")
def get_customer(customer_ref: str, request: Request) -> dict[str, Any]:
    _check_caller_pii_permission(request)
    cust_svc, _, _, _, _ = _get_services(request)
    c = cust_svc.get_customer(customer_ref)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


@operations_router.post("/customers/import")
async def import_customers(request: Request, file: UploadFile | None = None) -> dict[str, Any]:
    cust_svc, _, _, _, _ = _get_services(request)
    if file is not None:
        content = (await file.read()).decode("utf-8", errors="replace")
    else:
        body = await request.body()
        content = body.decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")
    return cust_svc.import_customers_csv(content)


# --- 2. Campaign Endpoints ---
@operations_router.get("/campaigns")
def list_campaigns(request: Request, status: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
    _, camp_svc, _, _, _ = _get_services(request)
    return camp_svc.list_campaigns(status=status, region=region)


@operations_router.post("/campaigns")
async def create_campaign(request: Request) -> dict[str, Any]:
    _, camp_svc, _, _, _ = _get_services(request)
    data = await request.json()
    return camp_svc.create_campaign(
        name=data.get("name", "Untitled Campaign"),
        objective=data.get("objective", "App adoption"),
        script_version=data.get("scriptVersion") or data.get("script_version", "v1.0"),
        segment_size=data.get("segmentSize") or data.get("segment_size", 0),
        max_attempts=data.get("maxAttempts") or data.get("max_attempts", 3),
        retry_gap_hours=data.get("retryGapHours") or data.get("retry_gap_hours", 24),
        languages=data.get("languages", ["Hindi", "English"]),
        region=data.get("region", "All India"),
        status=data.get("status", "DRAFT"),
    )


@operations_router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    _, camp_svc, _, _, _ = _get_services(request)
    c = camp_svc.get_campaign(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c


@operations_router.patch("/campaigns/{campaign_id}")
async def patch_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    _, camp_svc, _, _, _ = _get_services(request)
    data = await request.json()
    try:
        return camp_svc.update_campaign(campaign_id, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")


@operations_router.post("/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    _, camp_svc, _, _, rep_svc = _get_services(request)
    try:
        res = camp_svc.start_campaign(campaign_id)
        rep_svc.record_audit("CAMPAIGN_STARTED", "CAMPAIGN", campaign_id)
        event_bus.publish("campaign_started", {"campaign_id": campaign_id})
        return res
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")


@operations_router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
    _, camp_svc, _, _, rep_svc = _get_services(request)
    try:
        res = camp_svc.pause_campaign(campaign_id)
        rep_svc.record_audit("CAMPAIGN_PAUSED", "CAMPAIGN", campaign_id)
        event_bus.publish("campaign_paused", {"campaign_id": campaign_id})
        return res
    except KeyError:
        raise HTTPException(status_code=404, detail="Campaign not found")


@operations_router.post("/campaigns/{campaign_id}/contacts/import")
async def import_campaign_contacts(campaign_id: str, request: Request, file: UploadFile | None = None) -> dict[str, Any]:
    _, camp_svc, _, _, _ = _get_services(request)
    if file is not None:
        content = (await file.read()).decode("utf-8", errors="replace")
    else:
        body = await request.body()
        content = body.decode("utf-8", errors="replace")
    return camp_svc.import_contacts_csv(campaign_id, content)


# --- 3. Call Endpoints ---
@operations_router.get("/calls")
def list_calls(
    request: Request,
    campaign_id: str | None = None,
    disposition: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    _, _, call_svc, _, _ = _get_services(request)
    return call_svc.list_calls(campaign_id=campaign_id, disposition=disposition, status=status, limit=limit, offset=offset)


@operations_router.get("/calls/export")
def export_calls(request: Request) -> Response:
    _, _, call_svc, _, _ = _get_services(request)
    csv_text = call_svc.export_calls_csv()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=calls_export.csv"},
    )


@operations_router.get("/calls/{call_id}")
def get_call(call_id: str, request: Request) -> dict[str, Any]:
    _check_caller_pii_permission(request)
    _, _, call_svc, _, _ = _get_services(request)
    c = call_svc.get_call(call_id)
    if not c:
        raise HTTPException(status_code=404, detail="Call not found")
    return c


@operations_router.get("/calls/{call_id}/transcript")
def get_call_transcript(call_id: str, request: Request) -> list[dict[str, Any]]:
    _check_caller_pii_permission(request)
    _, _, call_svc, _, _ = _get_services(request)
    return call_svc.get_call_transcript(call_id)


@operations_router.get("/calls/{call_id}/recording")
def get_call_recording(call_id: str, request: Request) -> FileResponse:
    _check_caller_pii_permission(request)
    _, _, call_svc, _, _ = _get_services(request)
    call = call_svc.get_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    sess_id = call.get("sessionId") or call_id
    rec_path = get_recording_path(sess_id)
    if not rec_path:
        # Create lightweight simulated WAV file for verification
        rec_path = Path(ensure_recording_exists(sess_id))
    return FileResponse(path=str(rec_path), media_type="audio/wav", filename=f"{call_id}.wav")


@operations_router.get("/recordings/{recording_id}")
def get_direct_recording(recording_id: str, request: Request) -> FileResponse:
    _check_caller_pii_permission(request)
    rec_path = Path(ensure_recording_exists(recording_id))
    return FileResponse(path=str(rec_path), media_type="audio/wav", filename=f"{recording_id}.wav")


# --- 4. Agent Endpoints ---
@operations_router.get("/agents")
def list_agents(request: Request, availability: str | None = None, team: str | None = None) -> dict[str, Any]:
    _, _, _, agent_svc, _ = _get_services(request)
    agents = agent_svc.list_agents(availability=availability, team=team)
    workloads = agent_svc.get_agent_workloads()
    return {
        "agents": agents,
        "workloads": workloads,
        "slaPolicies": SLA_POLICIES,
    }


@operations_router.patch("/agents/{agent_id}/status")
async def patch_agent_status(agent_id: str, request: Request) -> dict[str, Any]:
    _, _, _, agent_svc, rep_svc = _get_services(request)
    data = await request.json()
    avail = data.get("availability")
    if not avail:
        raise HTTPException(status_code=400, detail="availability is required")
    try:
        updated = agent_svc.update_agent_availability(agent_id, avail)
        rep_svc.record_audit("AGENT_STATUS_CHANGED", "AGENT", agent_id, detail=f"Availability set to {avail}")
        event_bus.publish("agent_status_changed", {"agent_id": agent_id, "availability": avail})
        return updated
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")


@operations_router.post("/agents/assign")
async def auto_assign_resource(request: Request) -> dict[str, Any]:
    _, _, _, agent_svc, _ = _get_services(request)
    data = await request.json()
    lang = data.get("language", "Hindi")
    cat = data.get("category", "APP_SUPPORT")
    best = agent_svc.find_best_agent(preferred_language=lang, issue_category=cat)
    if not best:
        raise HTTPException(status_code=404, detail="No suitable agent available")
    return {"assigned_agent": best}


# --- 5. Compliance & Audit Endpoints ---
@operations_router.get("/compliance/summary")
def get_compliance_summary(request: Request) -> dict[str, Any]:
    _, _, call_svc, _, _ = _get_services(request)
    calls = call_svc.list_calls(limit=100)
    consents = [
        {
            "callId": c["id"],
            "customerRef": c["customerRef"],
            "purpose": "Mobile app service call",
            "consented": c.get("consented", True),
            "recordedAt": c["startedAt"],
            "channel": "VOICE",
            "retentionUntil": c["startedAt"],
        }
        for c in calls
        if c.get("connected")
    ]
    return {"consents": consents, "egressLogs": []}


@operations_router.get("/audit")
def list_operational_audits(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    _, _, _, _, rep_svc = _get_services(request)
    return rep_svc.list_audits(limit=limit)


@operations_router.post("/audit")
async def record_operational_audit(request: Request) -> dict[str, Any]:
    _, _, _, _, rep_svc = _get_services(request)
    data = await request.json()
    return rep_svc.record_audit(
        action=data.get("action", "UI_ACTION"),
        resource_type=data.get("resourceType") or data.get("resource_type", "GENERAL"),
        resource_id=data.get("resourceId") or data.get("resource_id", "UI"),
        role=data.get("role") or data.get("actorRole", "OPS_MANAGER"),
        actor=data.get("actor", "OPS-001"),
        detail=data.get("detail", ""),
    )


# --- 6. Reporting & Scheduling Endpoints ---
@operations_router.get("/reports/kpi-summary")
def get_kpi_summary(request: Request, campaign_id: str | None = None) -> dict[str, Any]:
    _, _, _, _, rep_svc = _get_services(request)
    return rep_svc.get_kpi_summary(campaign_id=campaign_id)


@operations_router.get("/reports/schedules")
def get_report_schedules(request: Request) -> list[dict[str, Any]]:
    _, _, _, _, rep_svc = _get_services(request)
    return rep_svc.list_schedules()


@operations_router.post("/reports/schedules")
async def save_report_schedule(request: Request) -> dict[str, Any]:
    _, _, _, _, rep_svc = _get_services(request)
    data = await request.json()
    return rep_svc.save_schedule(data)


# --- 7. Full Combined Dashboard Snapshot ---
@operations_router.get("/snapshot")
def get_dashboard_snapshot(request: Request) -> dict[str, Any]:
    from kural.services.callback_service import CallbackService
    from kural.services.case_service import CaseService

    db: Database = request.app.state.database
    _, camp_svc, call_svc, agent_svc, rep_svc = _get_services(request)
    cb_svc = CallbackService(db)
    case_svc = CaseService(db)

    calls = call_svc.list_calls(limit=200)
    campaigns = camp_svc.list_campaigns()
    callbacks = cb_svc.list_callbacks()
    escalations = case_svc.list_cases()
    agents = agent_svc.list_agents()
    workloads = agent_svc.get_agent_workloads()
    audits = rep_svc.list_audits(limit=100)

    consents = [
        {
            "callId": c["id"],
            "customerRef": c["customerRef"],
            "purpose": "Mobile app service call",
            "consented": c.get("consented", True),
            "recordedAt": c["startedAt"],
            "channel": "VOICE",
            "retentionUntil": c["startedAt"],
        }
        for c in calls
        if c.get("connected")
    ]

    return {
        "calls": calls,
        "campaigns": campaigns,
        "callbacks": callbacks,
        "escalations": escalations,
        "agents": agents,
        "workloads": workloads,
        "slaPolicies": SLA_POLICIES,
        "consents": consents,
        "auditEvents": audits,
        "egressLogs": [],
    }
