import pytest

from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.persistence.repository import SqlAlchemyKuralRepository


@pytest.fixture(autouse=True)
def disable_external_llm_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the ordinary suite offline even when a developer has configured Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")


@pytest.fixture
def database() -> Database:
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    yield db
    db.dispose()


@pytest.fixture
def repository(database: Database) -> SqlAlchemyKuralRepository:
    return SqlAlchemyKuralRepository(database)
