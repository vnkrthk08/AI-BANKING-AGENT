"""FastAPI application entry point and dependency composition."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, PlainTextResponse

logger = logging.getLogger("kural.workers")
logging.getLogger("kural").setLevel(logging.INFO)

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
from kural.telephony.config import get_telephony_provider
from kural.telephony.router import telephony_router
from kural.notifications.service import NotificationService
from kural.notifications.router import notification_router


def create_app(repository: KuralRepository | None = None,
               llm_provider: LLMProvider | None = None,
               stt_provider: STTProvider | None = None,
               tts_provider: TTSProvider | None = None,
               realtime_stt_provider: RealtimeSTTProvider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio
        from kural.workers import WorkerRunner

        auth_svc = getattr(app.state, "auth_service", None)
        if auth_svc is not None:
            auth_svc.startup_cache_sync()
        runner_task = None
        if app.state.settings.run_workers:
            runner = WorkerRunner(app.state.database, app.state.notification_service, get_telephony_provider)
            app.state.worker_runner = runner
            runner_task = asyncio.create_task(runner.run())
        yield
        if runner_task is not None:
            app.state.worker_runner.stop()
            await asyncio.gather(runner_task, return_exceptions=True)
        close = getattr(app.state.tts_provider, "close", None)
        if close is not None:
            await close()
        close_stt = getattr(app.state.realtime_stt_provider, "close", None)
        if close_stt is not None:
            await close_stt()

    app = FastAPI(
        title="KURAL AVA",
        description="KURAL AVA voice banking operations API.",
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
    from kural.config import get_settings, validate_startup
    settings = get_settings()
    problems = validate_startup(settings)
    if problems:
        raise RuntimeError("Refusing to start: " + " | ".join(problems))
    app.state.settings = settings
    app.state.database.prepare_schema(auto_migrate=settings.auto_migrate)
    app.state.repository = repository
    app.state.callback_service = CallbackService(app.state.database)
    app.state.case_service = CaseService(app.state.database)
    app.state.customer_service = CustomerService(app.state.database)
    app.state.campaign_service = CampaignService(app.state.database)
    app.state.call_service = CallService(app.state.database)
    app.state.agent_service = AgentService(app.state.database)
    app.state.report_service = ReportService(app.state.database)
    app.state.auth_service = AuthService(app.state.database)
    app.state.notification_service = NotificationService(app.state.database)
    app.state.telephony_provider = get_telephony_provider()

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
    app.include_router(telephony_router)
    app.include_router(notification_router)
    from app.routers.system import system_router
    app.include_router(system_router)
    if app.state.settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=app.state.settings.cors_origins,
                           allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root() -> str:
        """Point visitors to the actual Vite AVA development interface."""
        return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AVA · KURAL</title>
</head>
<body><main><h1>KURAL AVA</h1><p>The AVA interface runs at
<a href="http://127.0.0.1:5173/">http://127.0.0.1:5173/</a>.</p></main></body></html>"""

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness: the process is up and can reach its database."""
        app.state.repository.health_check()
        return {"status": "ok", "service": "kural-ava", "environment": app.state.settings.app_env}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        """Readiness: database reachable, schema at Alembic head, auth cache synchronised."""
        from kural.security.revocation_cache import revocation_cache
        from app.routers.system import schema_status
        try:
            app.state.repository.health_check()
        except Exception:
            raise HTTPException(status_code=503, detail="Database unavailable")
        schema = schema_status(app.state.database)
        if not schema["at_head"]:
            raise HTTPException(status_code=503, detail="Database schema is not at the latest migration")
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


app = create_app()

