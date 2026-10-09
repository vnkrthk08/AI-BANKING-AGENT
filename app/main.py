"""FastAPI application entry point and dependency composition."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, PlainTextResponse

logger = logging.getLogger("kural.workers")

from kural.api import dashboard_router, router
from kural.api_operations import operations_router
from kural.persistence.database import Database
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.repositories import KuralRepository
from kural.providers.config import create_llm_provider
from kural.providers.contracts import LLMProvider
from kural.providers.voice_config import create_realtime_stt_provider, create_stt_provider, create_tts_provider
from kural.providers.contracts import RealtimeSTTProvider, STTProvider, TTSProvider
from kural.services.agent_service import AgentService
from kural.services.call_service import CallService
from kural.services.callback_service import CallbackService
from kural.services.campaign_service import CampaignService
from kural.services.case_service import CaseService
from kural.services.customer_service import CustomerService
from kural.services.report_service import ReportService
from kural.services.auth_service import AuthService
from app.routers.auth import auth_router


def create_app(repository: KuralRepository | None = None,
               llm_provider: LLMProvider | None = None,
               stt_provider: STTProvider | None = None,
               tts_provider: TTSProvider | None = None,
               realtime_stt_provider: RealtimeSTTProvider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio
        from datetime import datetime, timezone
        from sqlalchemy import select
        from kural.persistence.models import CallbackRow
        from kural.services.event_bus import event_bus

        stop_worker = asyncio.Event()

        async def callback_scheduler_worker():
            """Polls callbacks table every 10s for due callbacks so they reflect in dashboard."""
            while not stop_worker.is_set():
                try:
                    await asyncio.sleep(10)
                    db = getattr(app.state, "database", None)
                    if db is not None:
                        with db.session() as s:
                            now = datetime.now(timezone.utc)
                            due = s.scalars(
                                select(CallbackRow).where(
                                    CallbackRow.status == "SCHEDULED",
                                    CallbackRow.scheduled_at_utc.is_not(None),
                                    CallbackRow.scheduled_at_utc <= now,
                                )
                            ).all()
                            for cb in due:
                                cb.status = "DUE"
                                event_bus.publish("callback_due", {"callback_id": cb.callback_id})
                            if due:
                                s.commit()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("Callback scheduler worker encountered transient error: %s", exc)

        async def campaign_pacing_worker():
            """Polls active campaigns and processes queued contacts in background."""
            while not stop_worker.is_set():
                try:
                    await asyncio.sleep(5)
                    camp_svc = getattr(app.state, "campaign_service", None)
                    if camp_svc is not None:
                        active_camps = camp_svc.list_campaigns(status="ACTIVE")
                        for camp in active_camps:
                            queued = camp_svc.get_queued_contacts(camp["id"], batch_size=2)
                            for contact in queued:
                                import random
                                disp = random.choice(["CLOSED", "CLOSED", "CALLBACK_SCHEDULED", "BUSY", "NO_ANSWER"])
                                camp_svc.record_attempt(contact["contact_id"], disp, f"sim-{contact['contact_id']}")
                                event_bus.publish("campaign_progress", {
                                    "campaign_id": camp["id"],
                                    "contact_id": contact["contact_id"],
                                    "disposition": disp,
                                })
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("Campaign pacing worker encountered transient error: %s", exc)

        auth_svc = getattr(app.state, "auth_service", None)
        if auth_svc is not None:
            auth_svc.startup_cache_sync()

        cb_task = asyncio.create_task(callback_scheduler_worker())
        camp_task = asyncio.create_task(campaign_pacing_worker())
        yield
        stop_worker.set()
        cb_task.cancel()
        camp_task.cancel()
        await asyncio.gather(cb_task, camp_task, return_exceptions=True)

        close = getattr(app.state.tts_provider, "close", None)
        if close is not None:
            await close()
        close_stt = getattr(app.state.realtime_stt_provider, "close", None)
        if close_stt is not None:
            await close_stt()

    app = FastAPI(
        title="KURAL AVA",
        description="KURAL decision API for the AVA browser demo. Synthetic data only; not for production use.",
        version="0.3.0",
        lifespan=lifespan,
    )
    if repository is None:
        database = Database()
        repository = SqlAlchemyKuralRepository(database)
        app.state.database = database
    else:
        db = getattr(repository, "database", None)
        if db is None:
            db = Database()
        app.state.database = db
    from kural.persistence.models import Base
    Base.metadata.create_all(app.state.database.engine)
    app.state.repository = repository
    app.state.callback_service = CallbackService(app.state.database)
    app.state.case_service = CaseService(app.state.database)
    app.state.customer_service = CustomerService(app.state.database)
    app.state.campaign_service = CampaignService(app.state.database)
    app.state.call_service = CallService(app.state.database)
    app.state.agent_service = AgentService(app.state.database)
    app.state.report_service = ReportService(app.state.database)
    app.state.auth_service = AuthService(app.state.database)

    _seed_demo_operations(app.state.campaign_service, app.state.customer_service, app.state.call_service)

    app.state.llm_provider = llm_provider if llm_provider is not None else create_llm_provider()
    app.state.stt_provider = stt_provider if stt_provider is not None else create_stt_provider()
    app.state.tts_provider = tts_provider if tts_provider is not None else create_tts_provider()
    app.state.realtime_stt_provider = (
        realtime_stt_provider if realtime_stt_provider is not None else create_realtime_stt_provider()
    )
    app.include_router(router)
    app.include_router(dashboard_router)
    app.include_router(operations_router)
    app.include_router(auth_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root() -> str:
        """Point visitors to the actual Vite AVA development interface."""
        return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AVA · KURAL</title>
<script>window.location.replace('http://127.0.0.1:5173/')</script></head>
<body><main><h1>KURAL AVA</h1><p>The AVA interface runs at
<a href="http://127.0.0.1:5173/">http://127.0.0.1:5173/</a>.</p></main></body></html>"""

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        app.state.repository.health_check()
        return {"status": "ok", "service": "kural-ava", "mode": "prototype"}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        from kural.security.revocation_cache import revocation_cache
        if not revocation_cache.is_ready:
            raise HTTPException(status_code=503, detail="Service not ready: revocation cache synchronizing")
        return {"status": "ready"}

    @app.get("/metrics", response_class=PlainTextResponse, tags=["observability"])
    def prometheus_metrics() -> PlainTextResponse:
        from kural.telemetry.metrics import metrics_registry
        return PlainTextResponse(
            content=metrics_registry.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.websocket("/ws/voice/{session_id}")
    async def ws_voice_session(websocket: WebSocket, session_id: str) -> None:
        ticket = websocket.query_params.get("ticket")
        if not ticket:
            await websocket.close(code=1008, reason="Policy Violation: missing authentication ticket")
            return

        db = getattr(websocket.app.state, "database", None)
        if not db:
            await websocket.close(code=1008, reason="Policy Violation: database unavailable")
            return

        auth_svc = getattr(websocket.app.state, "auth_service", None)
        if not auth_svc:
            auth_svc = AuthService(db)
        valid = auth_svc.validate_and_burn_websocket_ticket(ticket, session_id)
        if not valid:
            await websocket.close(code=1008, reason="Policy Violation: ticket invalid or already consumed")
            return

        from kural.policy.calling_policy import CallingPolicyEngine
        is_real_customer = False
        repo = getattr(websocket.app.state, "repository", None)
        if repo:
            sess_obj = repo.get_session(session_id)
            if sess_obj and sess_obj.customer_ref and not (sess_obj.customer_ref.startswith("demo-") or sess_obj.customer_ref.startswith("test-")):
                is_real_customer = True

        stt_provider = getattr(websocket.app.state, "stt_provider", None)
        stt_type = getattr(stt_provider, "provider_type", "external_cloud")
        is_certified = getattr(stt_provider, "is_on_premise_certified", False)
        try:
            CallingPolicyEngine.validate_speech_processing_boundary(
                is_real_customer_session=is_real_customer,
                stt_provider_type=stt_type,
                is_on_premise_certified=is_certified,
            )
        except PermissionError as pe:
            await websocket.close(code=1008, reason=str(pe))
            return

        await websocket.accept()
        await websocket.send_json({"type": "session_connected", "session_id": session_id})
        try:
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except Exception:
            pass

    return app


def _seed_demo_operations(camp_svc: CampaignService, cust_svc: CustomerService, call_svc: CallService) -> None:
    try:
        existing_camps = camp_svc.list_campaigns()
        if not existing_camps:
            c1 = camp_svc.create_campaign(
                name="App adoption · Q4",
                objective="App adoption",
                script_version="v2.4",
                segment_size=8200,
                max_attempts=3,
                retry_gap_hours=24,
                languages=["Hindi", "English", "Tamil"],
                region="All India",
                status="ACTIVE",
            )
            c2 = camp_svc.create_campaign(
                name="App update follow-up",
                objective="App update",
                script_version="v1.8",
                segment_size=3400,
                max_attempts=2,
                retry_gap_hours=36,
                languages=["English", "Kannada", "Telugu"],
                region="South",
                status="ACTIVE",
            )
            cust1 = cust_svc.create_customer("Rajesh Sharma", "9876543210", "CUST-00001", preferred_language="Hindi", branch="Delhi NCR", region="North", app_status="INSTALLED", app_version="4.9.2")
            cust2 = cust_svc.create_customer("Priya Sundaram", "9876543211", "CUST-00002", preferred_language="Tamil", branch="Chennai South", region="South", app_status="NOT_INSTALLED")
            cust3 = cust_svc.create_customer("Amit Patel", "9876543212", "CUST-00003", preferred_language="Hindi", branch="Mumbai Metro", region="West", app_status="OUTDATED", app_version="4.7.0")
            cust_svc.create_customer("Sneha Reddy", "9876543213", "CUST-00004", preferred_language="Telugu", branch="Hyderabad Central", region="South", app_status="INSTALLED", app_version="5.0.0")
            cust_svc.create_customer("Rahul Mukherjee", "9876543214", "CUST-00005", preferred_language="Bengali", branch="Kolkata East", region="East", app_status="NOT_INSTALLED")

            camp_svc.add_contact(c1["id"], cust1["customer_ref"], cust1["phone"])
            camp_svc.add_contact(c1["id"], cust2["customer_ref"], cust2["phone"])
            camp_svc.add_contact(c1["id"], cust3["customer_ref"], cust3["phone"])
    except Exception:
        pass


app = create_app()
