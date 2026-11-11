"""Postgres access. Plain parameterized SQL (psycopg3), no ORM - small surface area, easy to audit. Every query uses placeholders
(%s), never string interpolation, so user input can never reach the SQL parser as code."""
import contextlib
import os

import psycopg
from psycopg.rows import dict_row

_pool_dsn = None


def _dsn():
    global _pool_dsn
    if _pool_dsn is None:
        from .config import settings
        _pool_dsn = settings.database_url
    return _pool_dsn


@contextlib.contextmanager
def connect():
    """One connection per request (Render Postgres free/starter tiers have a small connection cap; a real connection pool -
    e.g. psycopg_pool - is the first thing to add if this ever needs to scale past a hobby-project's traffic)."""
    with psycopg.connect(_dsn(), row_factory=dict_row, autocommit=False) as conn:
        yield conn


def run_migrations():
    """Applies migrations/*.sql in order, once each (tracked in a schema_migrations table). Safe to call on every boot."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mig_dir = os.path.join(here, "migrations")
    with connect() as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        cur.execute("SELECT name FROM schema_migrations")
        done = {r["name"] for r in cur.fetchall()}
        for name in sorted(os.listdir(mig_dir)):
            if not name.endswith(".sql") or name in done:
                continue
            with open(os.path.join(mig_dir, name), "r", encoding="utf-8") as f:
                cur.execute(f.read())
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
            conn.commit()
