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


# 代码新增而 init_db.sql 只在 Postgres 首次建库时执行的列:已部署的库(局域网盒子)
# 更新镜像后不会重放建表脚本,漏列会让 _fetch_project 的显式 SELECT 整个报错。
# 启动时补齐(全幂等)。新增列时同步维护这里和 init_db.sql。
_SCHEMA_GUARDS = (
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS selected_pm_performance JSONB",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS selected_td_performance JSONB",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS selected_evidence_pages JSONB",
)


def ensure_schema() -> None:
    """启动时把代码依赖的新列补进已存在的库(幂等;失败只告警不拦启动)。"""
    import logging

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for statement in _SCHEMA_GUARDS:
                    cur.execute(statement)
            conn.commit()
    except Exception:
        logging.getLogger(__name__).warning(
            "启动补列失败(数据库可能未就绪),依赖新列的功能在补列前不可用", exc_info=True
        )
