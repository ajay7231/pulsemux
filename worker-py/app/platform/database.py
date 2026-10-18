import os
from pathlib import Path
from functools import lru_cache
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from .models import Base


class Database:
    def __init__(self, url=None):
        data = Path(
            os.getenv(
                "PLATFORM_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")
            )
        )
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir = data
        url = url or os.getenv("DATABASE_URL", f'sqlite:///{data / "platform.db"}')
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_settings(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        if self.engine.dialect.name == "postgresql":
            with self.engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        # The initial schema is idempotent; subsequent changes use Alembic.
        Base.metadata.create_all(self.engine)


@lru_cache(maxsize=1)
def database():
    return Database()


def get_db():
    with database().Session() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
