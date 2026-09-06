"""As-of retrieval.

The temporal predicate is in the query that produces the candidates, not in a
filter applied to them afterwards. Two reasons, and the second is the one that
matters: a superseded version that is never scored cannot be accidentally
returned, and a filter applied after ranking is a filter some future code path
skips.

It also has to be on the same relation as the vector. A predicate that decides
which rows survive, evaluated on a joined table, cannot be pushed below the
scan, so the planner ranks first and filters second and the vector index buys
nothing. `chunks` carries both clocks for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgvector import Vector

from policy_asof import db, embed
from policy_asof.clock import AsOf


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    clause_version_id: str
    section: str
    text: str
    distance: float

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance


def as_of(conn: db.Conn, query: embed.Vector, at: AsOf, k: int = 5) -> list[Candidate]:
    db.with_vectors(conn)
    rows = conn.execute(
        """
        select id, clause_version_id, section_key, text,
               embedding <=> %(query)s as distance
        from chunks
        where embedding_model = %(model)s
          and valid_from <= %(valid_at)s
          and (valid_to is null or valid_to > %(valid_at)s)
          and recorded_at <= %(known_at)s
          and (recorded_until is null or recorded_until > %(known_at)s)
        order by embedding <=> %(query)s
        limit %(k)s
        """,
        {
            "query": Vector(query),
            "model": embed.model_name(),
            "valid_at": at.valid_at,
            "known_at": at.known_at,
            "k": k,
        },
    ).fetchall()
    return [
        Candidate(
            chunk_id=str(row["id"]),
            clause_version_id=str(row["clause_version_id"]),
            section=str(row["section_key"]),
            text=str(row["text"]),
            distance=float(row["distance"]),
        )
        for row in rows
    ]


def unfiltered(conn: db.Conn, query: embed.Vector, k: int = 5) -> list[Candidate]:
    """The same query with the predicate removed.

    Used by the ablation harness in phase 5, and by phase 3's measurement, so
    the two numbers come from the same code path rather than from two
    implementations that might differ in some other way.
    """
    db.with_vectors(conn)
    rows = conn.execute(
        """
        select id, clause_version_id, section_key, text,
               embedding <=> %(query)s as distance
        from chunks
        where embedding_model = %(model)s
        order by embedding <=> %(query)s
        limit %(k)s
        """,
        {"query": Vector(query), "model": embed.model_name(), "k": k},
    ).fetchall()
    return [
        Candidate(
            chunk_id=str(row["id"]),
            clause_version_id=str(row["clause_version_id"]),
            section=str(row["section_key"]),
            text=str(row["text"]),
            distance=float(row["distance"]),
        )
        for row in rows
    ]
