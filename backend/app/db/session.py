"""Database connection helper.

Deliberately small: the MVP computes everything on demand and uses the database
only for persistence of what it has served. The point of this module is that
the DSN - and therefore the engine - is a configuration value, so moving from
SQLite to PostgreSQL/TimescaleDB is a environment change rather than a rewrite.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from ..config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _sqlite_path(dsn: str) -> str:
    if not dsn.startswith("sqlite:///"):
        raise ValueError(
            f"Only sqlite DSNs are supported by the MVP connector, got '{dsn}'. "
            "For PostgreSQL/TimescaleDB, install psycopg and use a psycopg connection here - "
            "schema.sql runs unchanged on both engines."
        )
    return dsn.replace("sqlite:///", "", 1)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_sqlite_path(settings.database_url))
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite; PostgreSQL always enforces
    # them, so turning them on keeps the two engines behaving alike.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    """Create all tables if they do not exist."""
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
