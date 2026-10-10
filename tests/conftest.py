import pytest

from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.persistence.repository import SqlAlchemyKuralRepository


@pytest.fixture(autouse=True)
def disable_external_llm_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the ordinary suite offline even when a developer has configured Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")


@pytest.fixture(autouse=True)
def functional_test_principal(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Functional API tests run as an authenticated operator.

    Tests marked ``real_auth`` exercise genuine token authentication and RBAC enforcement
    (see tests/test_rbac_enforcement.py and tests/test_phase4_m41_auth.py).
    """
    if request.node.get_closest_marker("real_auth"):
        return
    from kural.security import deps

    principal = deps.Principal(user_id="test-user", username="test.operator", role="OPS_MANAGER", branch="Test")
    monkeypatch.setattr(deps, "_resolve_principal", lambda request, authorization: principal)
    monkeypatch.setattr(deps, "_check", lambda role, permission: None)


@pytest.fixture
def database() -> Database:
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    yield db
    db.dispose()


@pytest.fixture
def repository(database: Database) -> SqlAlchemyKuralRepository:
    return SqlAlchemyKuralRepository(database)


def seed_test_agents(database: Database, count: int = 16) -> None:
    """Register a roster for routing tests (the runtime never seeds agents)."""
    from kural.services.agent_service import AgentService

    svc = AgentService(database)
    langs = [["Hindi", "English"], ["Tamil", "English"], ["English", "Marathi"]]
    for i in range(count):
        svc.create_agent(name=f"Test Agent {i + 1}", languages=langs[i % 3],
                         skills=["APP_SUPPORT", "GENERAL_SUPPORT"], availability="AVAILABLE",
                         agent_id=f"AG-{i + 1:03d}")


@pytest.fixture
def sandbox_dialing(monkeypatch: pytest.MonkeyPatch):
    """Explicitly labelled test environment: sandbox telephony + test-number allowlist."""
    from kural.config import reload_settings
    from kural.telephony.config import set_telephony_provider
    from kural.telephony.sandbox import SandboxTelephonyProvider

    def enable(*numbers: str) -> SandboxTelephonyProvider:
        monkeypatch.setenv("TELEPHONY_DIAL_ALLOWLIST", ",".join(numbers))
        reload_settings()
        provider = SandboxTelephonyProvider()
        set_telephony_provider(provider)
        return provider

    yield enable
    set_telephony_provider(None)  # type: ignore[arg-type]
    monkeypatch.delenv("TELEPHONY_DIAL_ALLOWLIST", raising=False)
    reload_settings()
