"""Connection handling.

One pool, opened lazily, closed at exit. `psycopg_pool` runs worker threads that
are not daemon threads, so without the `atexit` hook every short script ends in a
wall of "couldn't stop thread" warnings printed after its useful output, which is
exactly where they are most likely to be read as a failure.
"""

from __future__ import annotations

import atexit
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DSN = os.environ.get("POLICY_ASOF_DSN", "postgresql://policy:policy@localhost:5438/policy_asof")

Row = dict[str, Any]
Conn = psycopg.Connection[Row]

_pool: ConnectionPool[Conn] | None = None


def pool() -> ConnectionPool[Conn]:
    global _pool
    if _pool is None:
        _pool = ConnectionPool[Conn](
            DSN,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        # Registered in the same breath as the construction, not somewhere else.
        atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[Conn]:
    with pool().connection() as conn:
        yield conn


def one(rows: list[Row]) -> Row:
    """The row a query must have returned.

    A missing row here is a bug rather than a branch, so say that once instead
    of asserting at every call site.
    """
    if len(rows) != 1:
        raise LookupError(f"expected exactly one row, got {len(rows)}")
    return rows[0]
