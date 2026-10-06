"""FastAPI application entry point and dependency composition."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from kural.api import dashboard_router, router
from kural.persistence.database import Database
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.repositories import KuralRepository
from kural.providers.config import create_llm_provider
from kural.providers.contracts import LLMProvider
from kural.providers.voice_config import create_realtime_stt_provider, create_stt_provider, create_tts_provider
from kural.providers.contracts import RealtimeSTTProvider, STTProvider, TTSProvider


def create_app(repository: KuralRepository | None = None,
               llm_provider: LLMProvider | None = None,
               stt_provider: STTProvider | None = None,
               tts_provider: TTSProvider | None = None,
               realtime_stt_provider: RealtimeSTTProvider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        close = getattr(app.state.tts_provider, "close", None)
        if close is not None:
            await close()
        close_stt = getattr(app.state.realtime_stt_provider, "close", None)
        if close_stt is not None:
            await close_stt()

    app = FastAPI(
        title="KURAL AVA",
        description="KURAL decision API for the AVA browser demo. Synthetic data only; not for production use.",
        version="0.2.0",
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
    from kural.services.callback_service import CallbackService
    from kural.services.case_service import CaseService
    app.state.callback_service = CallbackService(app.state.database)
    app.state.case_service = CaseService(app.state.database)
    app.state.llm_provider = llm_provider if llm_provider is not None else create_llm_provider()
    app.state.stt_provider = stt_provider if stt_provider is not None else create_stt_provider()
    app.state.tts_provider = tts_provider if tts_provider is not None else create_tts_provider()
    app.state.realtime_stt_provider = (
        realtime_stt_provider if realtime_stt_provider is not None else create_realtime_stt_provider()
    )
    app.include_router(router)
    app.include_router(dashboard_router)

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

    return app


app = create_app()
