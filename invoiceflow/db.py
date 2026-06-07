from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from invoiceflow.config import Settings, ensure_dirs
from invoiceflow.models import Base

_engine = None
SessionLocal = sessionmaker()


def init_db(settings: Settings):
    global _engine
    ensure_dirs(settings)
    _engine = create_engine(f"sqlite:///{settings.db_path}", future=True)

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(_engine)
    SessionLocal.configure(bind=_engine, future=True)
    return _engine


def get_engine():
    if _engine is None:
        raise RuntimeError("init_db() not called")
    return _engine
