import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url

@contextmanager
def db_conn():
    conn = psycopg2.connect(get_db_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
