from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.main import create_app
from kural.conversation.engine import KuralEngine
from kural.models import State
from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.persistence.repository import SqlAlchemyKuralRepository


def to_app_status(engine: KuralEngine) -> str:
    session, _ = engine.create_session()
    for answer in ("yes", "yes", "yes"):
        engine.turn(session.session_id, answer)
    return session.session_id


def test_session_persistence(repository: SqlAlchemyKuralRepository) -> None:
    session, _ = KuralEngine(repository).create_session("demo-002")
    loaded = repository.get_session(session.session_id)
    assert loaded is not None
    assert loaded.customer_ref == "demo-002"
    assert loaded.state == State.DISCLOSURE


def test_conversation_turn_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    detail = repository.get_session_detail(session.session_id)
    assert detail is not None
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["turn_order"] == 1
    assert detail["turns"][0]["intent"] == "AFFIRM"
    assert detail["turns"][0]["state"] == State.IDENTITY_CHECK.value


def test_case_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session_id = to_app_status(engine)
    engine.turn(session_id, "the app is installed")
    engine.turn(session_id, "update failed")
    response = engine.turn(session_id, "yes")
    stored = repository.list_cases()
    assert response.case_id is not None
    assert len(stored) == 1
    assert stored[0]["case_id"] == response.case_id
    assert stored[0]["customer_ref"] == "demo-001"
    assert stored[0]["callback_requested"] is True


def test_callback_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "busy")
    result = engine.turn(session.session_id, "yes, call me back")
    callbacks = repository.list_callbacks(session.session_id)
    assert result.callback_id is not None
    assert len(callbacks) == 1
    assert callbacks[0]["callback_id"] == result.callback_id
    assert callbacks[0]["case_id"] is None
    assert callbacks[0]["status"] == "REQUESTED"


def test_callback_requested_time_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "yes")
    engine.turn(session.session_id, "busy")
    requested_at = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    result = engine.turn(session.session_id, "yes", requested_at=requested_at)
    callback = repository.list_callbacks(session.session_id)[0]
    assert callback["callback_id"] == result.callback_id
    assert callback["requested_at"].isoformat() == requested_at.isoformat()


def test_audit_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "yes")
    events = repository.list_audit_events(session.session_id)
    assert events[0]["event_type"] == "session_start"
    assert any(event["event_type"] == "intent_detected" for event in events)
    assert all(event["session_id"] == session.session_id for event in events)


def test_redaction_happens_before_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "Please call code 123456")
    detail = repository.get_session_detail(session.session_id)
    assert detail is not None
    assert "123456" not in detail["turns"][0]["text"]
    assert "[REDACTED_OTP]" in detail["turns"][0]["text"]


def test_long_numeric_identifier_is_redacted_before_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "This is my card 4111 1111 1111 1111")
    detail = repository.get_session_detail(session.session_id)
    assert detail is not None
    assert "4111" not in detail["turns"][0]["text"]
    assert "[REDACTED_CARD]" in detail["turns"][0]["text"]
    assert "4111" not in str(repository.list_audit_events(session.session_id))


def test_sensitive_data_never_reaches_persistence(repository: SqlAlchemyKuralRepository) -> None:
    engine = KuralEngine(repository)
    session, _ = engine.create_session()
    engine.turn(session.session_id, "My OTP is 123456")
    detail = repository.get_session_detail(session.session_id)
    events = repository.list_audit_events(session.session_id)
    assert detail is not None
    assert "123456" not in str(detail)
    assert "123456" not in str(events)
    assert "[REDACTED_OTP]" in str(detail)


def test_api_session_retrieval_after_repository_restart(tmp_path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    first_db = Database(db_url)
    Base.metadata.create_all(first_db.engine)
    first_repository = SqlAlchemyKuralRepository(first_db)
    with TestClient(create_app(first_repository)) as client:
        session = client.post("/api/v1/sessions", json={"customer_ref": "demo-001"}).json()
        sid = session["session_id"]
        assert client.post(f"/api/v1/sessions/{sid}/messages", json={"text": "yes"}).status_code == 200
    first_db.dispose()

    second_db = Database(db_url)
    second_repository = SqlAlchemyKuralRepository(second_db)
    with TestClient(create_app(second_repository)) as client:
        fetched = client.get(f"/api/v1/sessions/{sid}")
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["session_id"] == sid
        assert body["current_state"] == State.IDENTITY_CHECK.value
        assert body["turns"][0]["text"] == "yes"
        assert client.get(f"/api/v1/audit/{sid}").status_code == 200
    second_db.dispose()

