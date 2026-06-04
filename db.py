import os
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("RENDER_DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not url:
        raise RuntimeError("Missing DATABASE_URL environment variable.")
    # Render sometimes provides postgres://; psycopg2 accepts it, but normalize for consistency.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@contextmanager
def get_conn():
    conn = psycopg2.connect(get_database_url(), sslmode=os.getenv("PGSSLMODE", "require"))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor(dict_cursor: bool = True):
    with get_conn() as conn:
        cursor_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
