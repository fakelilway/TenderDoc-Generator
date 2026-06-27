from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2 import pool as pg_pool

from core.config import settings

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _create_pool() -> pg_pool.ThreadedConnectionPool:
    # maxconn=20:ThreadedConnectionPool 满即抛 PoolError(不排队),突发并发(上传+轮询+生成)
    # 下 10 个偏紧。20 仍远低于 Postgres 默认 max_connections=100,留足缓冲。
    if settings.database_url:
        return pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=settings.database_url,
        )
    return pg_pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=20,
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        with _pool_lock:
            if _pool is None or _pool.closed:
                _pool = _create_pool()
    return _pool


@contextmanager
def get_db_connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a pooled connection; rollback on error, return to pool on exit.

    Drop-in replacement for ``psycopg2.connect(...)`` used as a context
    manager: commits are still the caller's responsibility (or use the
    connection's own context manager semantics inside).
    """
    db_pool = _get_pool()
    conn = db_pool.getconn()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db_pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def close_pool() -> None:
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.closeall()
    _pool = None
