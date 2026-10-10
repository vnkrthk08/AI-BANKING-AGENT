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

    def prepare_schema(self, auto_migrate: bool = True) -> None:
        """Bring the schema to the Alembic head.

        In-memory databases are created directly from the models. File/PostgreSQL databases
        are migrated with Alembic; a pre-Alembic database created by ``create_all`` is stamped
        at the revision its columns correspond to before upgrading.
        """
        from sqlalchemy import inspect

        from kural.persistence.models import Base
        if self.url in {"sqlite://", "sqlite:///:memory:"}:
            Base.metadata.create_all(self.engine)
            return
        if not auto_migrate:
            return
        from pathlib import Path
        from alembic import command
        from alembic.config import Config

        root = Path(__file__).resolve().parents[2]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "migrations"))
        cfg.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        cfg.attributes["configure_logger"] = False
        insp = inspect(self.engine)
        tables = set(insp.get_table_names())
        if tables and "alembic_version" not in tables:
            user_cols = {c["name"] for c in insp.get_columns("users")} if "users" in tables else set()
            if "phone" in user_cols:
                command.stamp(cfg, "head")
            elif "notifications" in tables:
                command.stamp(cfg, "0004_notifications_schema")
            else:
                Base.metadata.create_all(self.engine)
                command.stamp(cfg, "head")
        command.upgrade(cfg, "head")

    def create_tables(self) -> None:
        from kural.persistence.models import Base
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
