"""HTTP endpoints using the KURAL repository abstraction."""

import base64
import asyncio
import inspect
import logging
from typing import Any

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from kural.conversation.engine import KuralEngine
from kural.models import SessionCreateRequest, SessionResponse, TurnRequest, TurnResponse, VoiceTurnResponse
from kural.persistence.database import Database
from kural.repositories import KuralRepository
from kural.services.callback_service import CallbackDraft, CallbackService, KOLKATA_TZ
from kural.services.case_service import CaseService
from kural.services.event_bus import event_bus
from kural.voice.orchestrator import RealtimeVoiceOrchestrator
from fastapi import Depends
from kural.security.deps import Principal, require

router = APIRouter(prefix="/api/v1", tags=["conversation"])
dashboard_router = APIRouter(prefix="/api", tags=["dashboard"])
logger = logging.getLogger(__name__)
MAX_VOICE_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_VOICE_MIME_TYPES = {
    "audio/webm": ("customer.webm", "audio/webm"),
    "audio/ogg": ("customer.ogg", "audio/ogg"),
    "audio/wav": ("customer.wav", "audio/wav"),
    "audio/x-wav": ("customer.wav", "audio/wav"),
    "audio/mp4": ("customer.m4a", "audio/mp4"),
    "audio/mpeg": ("customer.mp3", "audio/mpeg"),
    "audio/aac": ("customer.aac", "audio/aac"),
}


def _repository(request: Request) -> KuralRepository:
    return request.app.state.repository


@router.post("/sessions", response_model=SessionResponse)
def create_session(request: Request, payload: SessionCreateRequest | None = None, principal: Principal = Depends(require("voice:operate"))) -> SessionResponse:
    customer_ref = payload.customer_ref if payload else "demo-001"
    try:
        conversation, greeting = KuralEngine(_repository(request)).create_session(customer_ref)
    except KeyError as error:
        raise HTTPException(status_code=400, detail="Unknown synthetic customer reference") from error
    call_svc = getattr(request.app.state, "call_service", None)
    if call_svc:
        try:
            call_svc.create_call_record(session_id=conversation.session_id, customer_ref=conversation.customer_ref)
        except Exception:
            pass
    return SessionResponse(session_id=conversation.session_id, state=conversation.state,
                           response=greeting, customer_ref=conversation.customer_ref)


@router.post("/sessions/{session_id}/messages", response_model=TurnResponse)
@router.post("/sessions/{session_id}/turns", response_model=TurnResponse, include_in_schema=False)
def submit_message(session_id: str, payload: TurnRequest, request: Request, principal: Principal = Depends(require("voice:operate"))) -> TurnResponse:
    try:
        turn = KuralEngine(
            _repository(request), llm_provider=request.app.state.llm_provider,
        ).turn(
            session_id, payload.text, payload.confidence, payload.requested_at,
        )
        call_svc = getattr(request.app.state, "call_service", None)
        if call_svc and getattr(turn, "ended", False):
            try:
                call_svc.update_call_by_session(session_id, {
                    "disposition": getattr(turn, "intent", None),
                    "status": "COMPLETED",
                    "kural_state": getattr(turn, "state", None),
                    "callback_id": getattr(turn, "callback_id", None),
                    "escalation_id": getattr(turn, "case_id", None),
                })
            except Exception:
                pass
        return turn
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error


async def _process_voice_audio(
    request: Request, session_id: str, audio_bytes: bytes, mime_type: str,
) -> VoiceTurnResponse:
    repository = _repository(request)
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    audio_format = SUPPORTED_VOICE_MIME_TYPES.get(mime_type)
    if audio_format is None:
        raise HTTPException(status_code=415, detail="Unsupported audio format. Record a WebM voice clip and try again.")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="The audio recording is empty.")
    if len(audio_bytes) > MAX_VOICE_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The recording is too large. Keep voice turns under 30 seconds.")

    try:
        transcription = await run_in_threadpool(
            request.app.state.stt_provider.transcribe,
            audio_bytes,
            filename=audio_format[0],
            content_type=audio_format[1],
        )
    except Exception as error:
        # SDK exceptions can include request data; expose only a generic service error.
        logger.warning("Voice STT failed error_type=%s", type(error).__name__)
        raise HTTPException(status_code=502, detail="Speech recognition failed. Please try again.") from None

    transcript = transcription.text if hasattr(transcription, "text") else str(transcription)
    language_code = getattr(transcription, "language_code", None)
    if not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech was detected. Please try again.")

    try:
        turn = await run_in_threadpool(
            KuralEngine(repository, llm_provider=request.app.state.llm_provider).turn,
            session_id,
            transcript,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error

    return VoiceTurnResponse(
        session_id=session_id,
        transcript=turn.sanitized_user_text,
        language_code=language_code,
        intent=turn.intent,
        state=turn.state,
        response=turn.response,
        ended=turn.ended,
        case_id=turn.case_id,
        callback_id=turn.callback_id,
        policy_decision=turn.policy_decision,
        audio_content_type=getattr(request.app.state.tts_provider, "content_type", "audio/mpeg"),
    )


async def _iter_tts_chunks(request: Request, text: str):
    provider = request.app.state.tts_provider
    stream = getattr(provider, "stream", None)
    if callable(stream):
        async for chunk in stream(text):
            if chunk:
                yield bytes(chunk)
        return

    # Compatibility for injected/third-party TTS implementations with the old complete-audio contract.
    synthesize = getattr(provider, "synthesize", None)
    if not callable(synthesize):
        raise RuntimeError("TTS provider has no supported synthesis method")
    if inspect.iscoroutinefunction(synthesize):
        result = await synthesize(text)
    else:
        result = await run_in_threadpool(synthesize, text)
    if result:
        yield bytes(result)


async def _collect_tts(request: Request, response: VoiceTurnResponse) -> VoiceTurnResponse:
    chunks: list[bytes] = []
    try:
        async for chunk in _iter_tts_chunks(request, response.response):
            chunks.append(chunk)
        if not chunks:
            raise ValueError("TTS returned an empty stream")
        response.audio_base64 = base64.b64encode(b"".join(chunks)).decode("ascii")
    except Exception as error:
        logger.warning("Voice TTS failed error_type=%s", type(error).__name__)
        response.tts_error = "AVA speech audio is unavailable right now. You can still read the response above."
    return response


@router.post("/voice/turn", response_model=VoiceTurnResponse)
async def submit_voice_turn(
    request: Request,
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    _p: Principal = Depends(require("voice:operate")),
) -> VoiceTurnResponse:
    mime_type = (audio.content_type or "").split(";", 1)[0].strip().lower()
    audio_bytes = await audio.read(MAX_VOICE_AUDIO_BYTES + 1)
    result = await _process_voice_audio(request, session_id, audio_bytes, mime_type)
    return await _collect_tts(request, result)


@router.websocket("/voice/turn/stream")
async def submit_streaming_voice_turn(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        start = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if not isinstance(start, dict) or start.get("type") != "start":
            await websocket.send_json({"type": "error", "detail": "Start a voice turn before sending audio."})
            return
        session_id = start.get("session_id")
        mime_type = str(start.get("content_type", "audio/webm")).split(";", 1)[0].strip().lower()
        if not isinstance(session_id, str) or not session_id:
            await websocket.send_json({"type": "error", "detail": "A valid session is required."})
            return
        audio_bytes = await asyncio.wait_for(websocket.receive_bytes(), timeout=35)
        result = await _process_voice_audio(websocket, session_id, audio_bytes, mime_type)
        await websocket.send_json({"type": "metadata", "data": result.model_dump(mode="json")})
        chunks_sent = False
        try:
            async for chunk in _iter_tts_chunks(websocket, result.response):
                chunks_sent = True
                await websocket.send_bytes(chunk)
            if not chunks_sent:
                raise ValueError("TTS returned an empty stream")
            await websocket.send_json({"type": "audio_complete"})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Voice TTS stream failed error_type=%s", type(error).__name__)
            await websocket.send_json({
                "type": "tts_error",
                "detail": "AVA speech audio is unavailable right now. You can still read the response above.",
            })
            await websocket.send_json({"type": "audio_complete"})
    except HTTPException as error:
        await websocket.send_json({"type": "error", "detail": error.detail})
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "detail": "Voice turn timed out. Please try again."})
    except WebSocketDisconnect:
        return
    except Exception as error:
        logger.warning("Voice WebSocket turn failed error_type=%s", type(error).__name__)
        try:
            await websocket.send_json({"type": "error", "detail": "Voice turn failed. Please try again."})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/voice/realtime")
async def realtime_voice_call(websocket: WebSocket) -> None:
    """Persistent PCM microphone/STT/KURAL/TTS call transport (ticket-authenticated)."""
    from kural.security.deps import authorize_stream
    session_q = websocket.query_params.get("session_id", "")
    if authorize_stream(websocket, session_q, "voice:operate") is None:
        await websocket.close(code=1008, reason="Authentication ticket required")
        return
    await websocket.accept()
    try:
        start = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if not isinstance(start, dict) or start.get("type") != "start":
            await websocket.send_json({"type": "voice_error", "detail": "Start a voice call before sending microphone audio."})
            return
        session_id = start.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id != session_q:
            await websocket.send_json({"type": "voice_error", "detail": "A valid KURAL session is required."})
            return
        provider = websocket.app.state.realtime_stt_provider
        connection_context = provider.connect()
        async with asyncio.timeout(18):
            stt_session = await connection_context.__aenter__()
        try:
            orchestrator = RealtimeVoiceOrchestrator(
                websocket,
                websocket.app.state.repository,
                stt_session,
                websocket.app.state.tts_provider,
                websocket.app.state.llm_provider,
            )
            await orchestrator.run(session_id, resume=bool(start.get("resume", False)))
        finally:
            await connection_context.__aexit__(None, None, None)
    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        logger.warning("Realtime voice connection timed out")
        try:
            await websocket.send_json({"type": "voice_error", "detail": "Speech service connection timed out. Please reconnect."})
        except Exception:
            pass
    except Exception as error:
        logger.warning("Realtime voice connection failed error_type=%s", type(error).__name__)
        try:
            await websocket.send_json({
                "type": "voice_error",
                "detail": "Voice service is unavailable right now. You can continue with typed chat.",
                "fatal": True,
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, principal: Principal = Depends(require("call:read"))) -> dict[str, Any]:
    detail = _repository(request).get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


def _callback_service(request: Request) -> CallbackService:
    service = getattr(request.app.state, "callback_service", None)
    if service is None:
        db = getattr(request.app.state, "database", None)
        if db is None:
            db = getattr(_repository(request), "database", Database())
            request.app.state.database = db
        service = CallbackService(db)
        request.app.state.callback_service = service
    return service


def _case_service(request: Request) -> CaseService:
    service = getattr(request.app.state, "case_service", None)
    if service is None:
        db = getattr(request.app.state, "database", None)
        if db is None:
            db = getattr(_repository(request), "database", Database())
            request.app.state.database = db
        service = CaseService(db)
        request.app.state.case_service = service
    return service


# --- Callbacks Endpoints ---
@router.get("/callbacks")
@dashboard_router.get("/callbacks")
def list_callbacks(request: Request, session_id: str | None = None, principal: Principal = Depends(require("callback:read"))) -> list[dict[str, Any]]:
    return _callback_service(request).list_callbacks(session_id=session_id)


@router.get("/callbacks/{callback_id}")
@dashboard_router.get("/callbacks/{callback_id}")
def get_callback(callback_id: str, request: Request, principal: Principal = Depends(require("callback:read"))) -> dict[str, Any]:
    cb = _callback_service(request).get_callback(callback_id)
    if cb is None:
        raise HTTPException(status_code=404, detail="Callback not found")
    return cb


@router.post("/callbacks")
@dashboard_router.post("/callbacks")
async def create_callback(request: Request, principal: Principal = Depends(require("callback:manage"))) -> dict[str, Any]:
    data = await request.json()
    scheduled_utc_raw = data.get("scheduled_at_utc") or data.get("preferredAt")
    if scheduled_utc_raw:
        if isinstance(scheduled_utc_raw, str):
            scheduled_utc = datetime.fromisoformat(scheduled_utc_raw.replace("Z", "+00:00"))
        else:
            scheduled_utc = scheduled_utc_raw
    else:
        scheduled_utc = datetime.now(timezone.utc)

    scheduled_local = data.get("scheduled_at_local")
    if not scheduled_local:
        local_dt = scheduled_utc.astimezone(KOLKATA_TZ)
        scheduled_local = local_dt.strftime("%a %d %b, %I:%M %p IST")

    draft = CallbackDraft(
        scheduled_at_utc=scheduled_utc,
        scheduled_at_local=scheduled_local,
        raw_expression=data.get("raw_expression"),
        requested_text_normalized=data.get("requested_text_normalized"),
        reason=data.get("reason", "CUSTOMER_BUSY"),
        case_id=data.get("case_id"),
        rule=data.get("resolution_rule") or data.get("rule"),
        timezone=data.get("timezone", "Asia/Kolkata"),
        language=data.get("language", "en-IN"),
    )
    return _callback_service(request).upsert_callback(
        session_id=data.get("session_id") or data.get("call_id", "demo-call"),
        customer_ref=data.get("customer_ref") or data.get("customerRef", "demo-001"),
        draft=draft,
        idempotency_key=data.get("idempotency_key"),
        actor="SUBBU" if data.get("on_behalf_of_customer") else f"STAFF:{principal.actor}",
    )


@router.patch("/callbacks/{callback_id}")
@dashboard_router.patch("/callbacks/{callback_id}")
async def patch_callback(callback_id: str, request: Request, principal: Principal = Depends(require("callback:manage"))) -> dict[str, Any]:
    body = await request.body()
    patch = json.loads(body) if body else {}
    actor = f"STAFF:{principal.actor}"
    service = _callback_service(request)

    if "preferredAt" in patch or "scheduled_at_utc" in patch:
        new_val = patch.get("preferredAt") or patch.get("scheduled_at_utc")
        if isinstance(new_val, str):
            new_utc = datetime.fromisoformat(new_val.replace("Z", "+00:00"))
        else:
            new_utc = new_val
        new_local = patch.get("scheduled_at_local")
        if not new_local:
            new_local = new_utc.astimezone(KOLKATA_TZ).strftime("%a %d %b, %I:%M %p IST")
        return service.reschedule_callback(callback_id, new_utc, new_local, actor=actor)

    if patch.get("status") == "CANCELLED":
        return service.cancel_callback(callback_id, actor=actor)

    cb = service.get_callback(callback_id)
    if not cb:
        raise HTTPException(status_code=404, detail="Callback not found")
    return cb


@router.post("/callbacks/{callback_id}/reschedule")
@dashboard_router.post("/callbacks/{callback_id}/reschedule")
async def post_reschedule_callback(callback_id: str, request: Request, principal: Principal = Depends(require("callback:manage"))) -> dict[str, Any]:
    body = await request.body()
    data = json.loads(body) if body else {}
    scheduled_utc_raw = data.get("scheduled_at_utc") or data.get("preferredAt")
    if isinstance(scheduled_utc_raw, str):
        scheduled_utc = datetime.fromisoformat(scheduled_utc_raw.replace("Z", "+00:00"))
    else:
        scheduled_utc = scheduled_utc_raw
    scheduled_local = data.get("scheduled_at_local")
    if not scheduled_local:
        scheduled_local = scheduled_utc.astimezone(KOLKATA_TZ).strftime("%a %d %b, %I:%M %p IST")
    return _callback_service(request).reschedule_callback(
        callback_id, scheduled_utc, scheduled_local, actor=f"STAFF:{principal.actor}", enforce_policy=True,
    )


@router.post("/callbacks/{callback_id}/cancel")
@dashboard_router.post("/callbacks/{callback_id}/cancel")
async def post_cancel_callback(callback_id: str, request: Request, principal: Principal = Depends(require("callback:manage"))) -> dict[str, Any]:
    body = await request.body()
    data = json.loads(body) if body else {}
    actor = "SUBBU" if data.get("on_behalf_of_customer") else f"STAFF:{principal.actor}"
    try:
        return _callback_service(request).cancel_callback(callback_id, actor=actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="Callback not found")


# --- Cases Endpoints ---
@router.get("/cases")
@dashboard_router.get("/cases")
def get_cases(request: Request, principal: Principal = Depends(require("case:read"))) -> list[dict[str, Any]]:
    return _case_service(request).list_cases()


@dashboard_router.get("/escalations")
def get_escalations(request: Request, principal: Principal = Depends(require("case:read"))) -> list[dict[str, Any]]:
    return _case_service(request).list_cases()


@router.get("/cases/{case_id}")
@dashboard_router.get("/cases/{case_id}")
@dashboard_router.get("/escalations/{case_id}")
def get_case(case_id: str, request: Request, principal: Principal = Depends(require("case:read"))) -> dict[str, Any]:
    c = _case_service(request).get_case(case_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return c


@router.post("/cases")
@dashboard_router.post("/cases")
@dashboard_router.post("/escalations")
async def create_case(request: Request, principal: Principal = Depends(require("case:work"))) -> dict[str, Any]:
    data = await request.json()
    return _case_service(request).create_case(
        session_id=data.get("session_id") or data.get("call_id", "demo-call"),
        customer_ref=data.get("customer_ref") or data.get("customerRef", "demo-001"),
        issue_code=data.get("issue_code") or data.get("category", "UNKNOWN_ISSUE"),
        summary=data.get("summary") or data.get("description", ""),
        key_lines=data.get("key_lines"),
        actions_tried=data.get("actions_tried"),
        callback_id=data.get("callback_id"),
        idempotency_key=data.get("idempotency_key"),
        actor="SUBBU" if data.get("on_behalf_of_customer") else f"STAFF:{principal.actor}",
    )


@router.patch("/cases/{case_id}")
@dashboard_router.patch("/cases/{case_id}")
@dashboard_router.patch("/escalations/{case_id}")
async def patch_case(case_id: str, request: Request, principal: Principal = Depends(require("case:work"))) -> dict[str, Any]:
    patch = await request.json()
    try:
        return _case_service(request).update_case(case_id, patch, actor=principal.actor, actor_role=principal.role)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# --- Dashboard Real-time Events ---
@router.get("/events/sse")
@dashboard_router.get("/events/sse")
async def sse_events(request: Request) -> StreamingResponse:
    from kural.security.deps import authorize_stream
    if authorize_stream(request, "events", "dashboard:view") is None and authorize_stream(request, "events", "system:read") is None:
        raise HTTPException(status_code=401, detail="Event stream requires a ticket")

    async def sse_stream():
        async for topic, payload in event_bus.subscribe("*"):
            yield f"event: {topic}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@router.websocket("/events/ws")
@dashboard_router.websocket("/events/ws")
async def ws_events(websocket: WebSocket) -> None:
    from kural.security.deps import authorize_stream
    if authorize_stream(websocket, "events", "dashboard:view") is None:
        await websocket.close(code=1008, reason="Authentication ticket required")
        return
    await websocket.accept()
    try:
        async for topic, payload in event_bus.subscribe("*"):
            await websocket.send_json({"event": topic, "data": payload})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass


@router.get("/audit/{session_id}")
def get_audit(session_id: str, request: Request, principal: Principal = Depends(require("audit:read"))) -> list[dict[str, Any]]:
    repository = _repository(request)
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return repository.list_audit_events(session_id)


@router.websocket("/ws/voice/{session_id}")
async def ws_voice_session(websocket: WebSocket, session_id: str) -> None:
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=1008, reason="Policy Violation: missing authentication ticket")
        return

    db = getattr(websocket.app.state, "database", None)
    if not db:
        await websocket.close(code=1008, reason="Policy Violation: database unavailable")
        return

    from kural.services.auth_service import AuthService
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
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass


