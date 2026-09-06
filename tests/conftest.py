"""Database fixtures.

Per-test isolation from the first test that writes, rather than from the first
time two tests collide. Everything runs inside one transaction that is rolled
back, so no test can leave a row behind for the next one to trip over, and the
order the modules run in stops mattering.

The truncate list comes from the catalogue rather than from a literal, because
the literal went stale twice: once when `chunks` arrived and once when
`answer_citations` did, each time as a wall of setup errors in every database
test at once.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg import sql

from policy_asof import corpus, db, ingest

# Applied migrations are schema, not fixture state.
KEEP = {"schema_migrations"}


@pytest.fixture
def conn() -> Iterator[db.Conn]:
    with db.pool().connection() as connection:
        tables = [
            str(row["tablename"])
            for row in connection.execute(
                "select tablename from pg_tables where schemaname = 'public'"
            ).fetchall()
            if str(row["tablename"]) not in KEEP
        ]
        connection.execute(
            sql.SQL("truncate {}").format(
                sql.SQL(", ").join(sql.Identifier(table) for table in sorted(tables))
            )
        )
        yield connection
        connection.rollback()


@pytest.fixture
def ingested(conn: db.Conn) -> db.Conn:
    for doc in corpus.load():
        ingest.ingest_document(conn, doc)
    return conn
