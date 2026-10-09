"""Environment-configured SQLAlchemy engine and transaction factory."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()
DEFAULT_DATABASE_URL = "sqlite:///./kural_local.db"


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        options: dict[str, object] = {"pool_pre_ping": True}
        if self.url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if self.url in {"sqlite://", "sqlite:///:memory:"}:
                from sqlalchemy.pool import StaticPool
                options["poolclass"] = StaticPool
        elif self.url.startswith("postgresql"):
            options["pool_size"] = 60
            options["max_overflow"] = 12  # Exactly 72 max connections under Phase 4 budget
            options["pool_timeout"] = 10.0
            options["pool_recycle"] = 1800
        self.engine: Engine = create_engine(self.url, **options)
        if self.url.startswith("sqlite"):
            from sqlalchemy import event

            @event.listens_for(self.engine, "connect")
            def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
                cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        db_session = self.session_factory()
        try:
            yield db_session
        finally:
            db_session.close()

    def create_tables(self) -> None:
        from kural.persistence.models import Base
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
