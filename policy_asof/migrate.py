"""Apply the SQL migrations, in order, once each.

Migrations are the only way the schema comes into being. `check_setup.py` is a
convenience for a person and nothing at runtime may depend on it having run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from policy_asof import db

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

LEDGER = """
create table if not exists schema_migrations (
    filename    text        primary key,
    applied_at  timestamptz not null default now()
)
"""


def pending(conn: db.Conn) -> list[Path]:
    conn.execute(LEDGER)
    applied = {row["filename"] for row in conn.execute("select filename from schema_migrations")}
    return [path for path in sorted(MIGRATIONS.glob("*.sql")) if path.name not in applied]


def apply(conn: db.Conn, path: Path) -> None:
    # psycopg 3.3 types `execute`'s query as LiteralString so that a query
    # cannot be assembled from a variable that might hold request data. A
    # migration runner reads its SQL from disk and legitimately trips that, and
    # this is the only place in the project allowed to.
    #
    # The pragma is pyright's and not mypy's on purpose. mypy erases
    # LiteralString, so it accepts this line, and it also rejects
    # `cast(LiteralString, ...)` as a redundant cast to str. Only pyright sees
    # the guarantee psycopg is trying to give, which is why it is in CI.
    conn.execute(path.read_text())  # pyright: ignore[reportCallIssue, reportArgumentType]
    conn.execute(
        "insert into schema_migrations (filename) values (%s)",
        (path.name,),
    )


def main() -> int:
    with db.connection() as conn:
        outstanding = pending(conn)
        if not outstanding:
            print("schema up to date")
            return 0
        for path in outstanding:
            print(f"applying {path.name}")
            apply(conn, path)
    print(f"applied {len(outstanding)} migration(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
