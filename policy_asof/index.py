"""Write the retrieval relation from the version chains.

One chunk per clause version, carrying both clocks. The point of the copy is
that the temporal predicate and the vector end up on the same relation, so the
predicate can run before anything is ranked instead of filtering afterwards.
"""

from __future__ import annotations

import sys
import uuid

from pgvector import Vector

from policy_asof import db, embed


def declared_dimension(conn: db.Conn) -> int:
    """The dimension the schema was migrated with, read rather than assumed."""
    row = db.one(
        conn.execute(
            """
            select atttypmod as dims
            from pg_attribute
            where attrelid = 'chunks'::regclass and attname = 'embedding'
            """
        ).fetchall()
    )
    return int(row["dims"])


def build(conn: db.Conn, *, rebuild: bool = False) -> int:
    """Embed every clause version that has no chunk yet. Returns how many.

    Idempotent by (version, model), so switching models adds a set rather than
    overwriting one, and re-running after an ingest costs one query.
    """
    db.with_vectors(conn)
    model = embed.model_name()
    dims = declared_dimension(conn)

    if rebuild:
        conn.execute("delete from chunks where embedding_model = %s", (model,))

    rows = conn.execute(
        """
        select v.id, v.section_key, v.text, v.valid_from, v.valid_to,
               v.recorded_at, v.recorded_until
        from clause_versions v
        where not exists (
            select 1 from chunks c
            where c.clause_version_id = v.id and c.embedding_model = %s
        )
        order by v.section_key, v.version_no
        """,
        (model,),
    ).fetchall()
    if not rows:
        return 0

    vectors = embed.embed([str(row["text"]) for row in rows], input_type="document")

    for row, vector in zip(rows, vectors, strict=True):
        if len(vector) != dims:
            raise ValueError(
                f"{model} returns {len(vector)} dimensions and chunks.embedding is "
                f"vector({dims}). Changing embedding model means a migration."
            )
        conn.execute(
            """
            insert into chunks
                (id, clause_version_id, section_key, text, valid_from, valid_to,
                 recorded_at, recorded_until, embedding, embedding_model)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.uuid4(),
                row["id"],
                row["section_key"],
                row["text"],
                row["valid_from"],
                row["valid_to"],
                row["recorded_at"],
                row["recorded_until"],
                Vector(vector),
                model,
            ),
        )
    return len(rows)


def main() -> int:
    with db.connection() as conn:
        written = build(conn)
    print(f"indexed {written} version(s)" if written else "index up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
