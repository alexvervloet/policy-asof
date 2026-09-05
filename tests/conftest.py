"""Database fixtures.

Per-test isolation from the first test that writes, rather than from the first
time two tests collide. Everything runs inside one transaction that is rolled
back, so no test can leave a row behind for the next one to trip over, and the
order the modules run in stops mattering.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from policy_asof import corpus, db, ingest


@pytest.fixture
def conn() -> Iterator[db.Conn]:
    with db.pool().connection() as connection:
        connection.execute("truncate clause_versions, documents")
        yield connection
        connection.rollback()


@pytest.fixture
def ingested(conn: db.Conn) -> db.Conn:
    for doc in corpus.load():
        ingest.ingest_document(conn, doc)
    return conn
