"""Named ways to remove one layer, applied at runtime.

Monkeypatches rather than edits, so a break is reversible, scriptable, and can
be applied to a checked-out tree without leaving anything behind to forget about.

This exists because of one number in a sibling project: twenty-one trajectory
evals, delete the fence around untrusted tool output, and nineteen still pass.
Redundancy is the point of defence in depth, and redundancy makes each
individual layer invisible to outcome testing. The only way to know which layer
is load-bearing is to remove it and watch.

Set `POLICY_ASOF_BREAK=<name>` and both the gate and the test suite apply it at
import.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from pgvector import Vector

from policy_asof import answer, db, embed, fence, read, resolve, retrieve
from policy_asof.clock import AsOf
from policy_asof.read import Outcome
from policy_asof.resolve import Resolution, Resolved


def _patch(module: object, name: str, replacement: object) -> None:
    """`setattr` rather than assignment.

    Both type checkers are right to object to rebinding a module's function, and
    silencing them ten times over would train me to silence the eleventh, which
    would be a real one. Going through `setattr` says "this is deliberate
    reflection" once, here, instead.
    """
    setattr(module, name, replacement)


def drop_temporal_predicate() -> None:
    """L2. Retrieval stops asking what time it is."""

    def unfiltered(
        conn: db.Conn, query: list[float], at: AsOf, k: int = 5
    ) -> list[retrieve.Candidate]:
        del at
        return retrieve.unfiltered(conn, query, k)

    _patch(retrieve, "as_of", unfiltered)


def collapse_two_clocks() -> None:
    """L2, the other half. Transaction time is ignored, so the store answers
    with what it believes now whatever the question asked about."""

    def one_clock(
        conn: db.Conn, query: list[float], at: AsOf, k: int = 5
    ) -> list[retrieve.Candidate]:
        db.with_vectors(conn)
        rows = conn.execute(
            """
            select id, clause_version_id, section_key, text,
                   embedding <=> %(query)s as distance
            from chunks
            where embedding_model = %(model)s
              and valid_from <= %(valid_at)s
              and (valid_to is null or valid_to > %(valid_at)s)
              and recorded_until is null
            order by embedding <=> %(query)s
            limit %(k)s
            """,
            {
                "query": _vector(query),
                "model": _model(),
                "valid_at": at.valid_at,
                "k": k,
            },
        ).fetchall()
        return [retrieve.candidate_from(row) for row in rows]

    _patch(retrieve, "as_of", one_clock)


def post_filter_instead_of_candidate_filter() -> None:
    """L2, structurally. The same predicate, applied after ranking instead of
    inside the fetch. The answers that survive are correct; the ones that fall
    off the end of k are simply gone."""

    def after(conn: db.Conn, query: list[float], at: AsOf, k: int = 5) -> list[retrieve.Candidate]:
        candidates = retrieve.unfiltered(conn, query, k)
        rows = {
            str(row["id"]): row
            for row in conn.execute(
                """
                select id, valid_from, valid_to, recorded_at, recorded_until
                from clause_versions
                where valid_from <= %(valid_at)s
                  and (valid_to is null or valid_to > %(valid_at)s)
                  and recorded_at <= %(known_at)s
                  and (recorded_until is null or recorded_until > %(known_at)s)
                """,
                {"valid_at": at.valid_at, "known_at": at.known_at},
            ).fetchall()
        }
        return [c for c in candidates if c.clause_version_id in rows]

    _patch(retrieve, "as_of", after)


def default_missing_date_to_today() -> None:
    """L1. Anything the parser cannot pin becomes today, silently."""
    original = resolve.resolve

    def never_refuse(question: str, now: datetime) -> Resolved:
        result = original(question, now)
        if result.outcome is Resolution.AMBIGUOUS:
            return Resolved(Resolution.ASSUMED_TODAY, AsOf(valid_at=now.date(), known_at=now))
        return result

    _patch(resolve, "resolve", never_refuse)
    _patch(answer, "resolve", never_refuse)


def drop_distance_floor() -> None:
    """L6, the per-topic half. Nothing is ever too far away to answer from."""
    answer.FLOOR = 1.0


def drop_lapse_detector() -> None:
    """L6, the other half. A lapsed clause stops being distinguishable from a
    topic the handbook never covered."""
    answer.LAPSE_GAP = 9.0


def drop_coverage_check() -> None:
    """L6, the global half. Every instant looks covered."""

    def always_covered(conn: db.Conn, at: AsOf) -> Outcome:
        del conn, at
        return Outcome.IN_FORCE

    _patch(read, "coverage", always_covered)


def drop_fence_neutralisation() -> None:
    """L7. Marker-shaped text in a document reaches the prompt intact."""

    def untouched(text: str) -> str:
        return text

    _patch(fence, "neutralise", untouched)


def fixed_fence_token() -> None:
    """L7, the other half. The delimiter becomes a string an attacker can type."""

    def constant(request_id: str) -> str:
        del request_id
        return "0000000000000000"

    _patch(fence, "token", constant)


def drop_citation_storage() -> None:
    """L5. The answer is stored without what it was allowed to draw on."""
    original = answer.store

    def without(conn: db.Conn, result: answer.Answer, *, asked_at: datetime) -> None:
        original(conn, replace(result, citations=()), asked_at=asked_at)

    _patch(answer, "store", without)


def _vector(query: list[float]) -> Vector:
    return Vector(query)


def _model() -> str:
    return embed.model_name()


BREAKS: dict[str, Callable[[], None]] = {
    "drop-temporal-predicate": drop_temporal_predicate,
    "collapse-two-clocks": collapse_two_clocks,
    "post-filter-instead-of-candidate-filter": post_filter_instead_of_candidate_filter,
    "default-missing-date-to-today": default_missing_date_to_today,
    "drop-distance-floor": drop_distance_floor,
    "drop-lapse-detector": drop_lapse_detector,
    "drop-coverage-check": drop_coverage_check,
    "drop-fence-neutralisation": drop_fence_neutralisation,
    "fixed-fence-token": fixed_fence_token,
    "drop-citation-storage": drop_citation_storage,
}


def apply_from_env() -> str | None:
    name = os.environ.get("POLICY_ASOF_BREAK")
    if not name:
        return None
    if name not in BREAKS:
        raise KeyError(f"unknown break {name!r}. Known: {', '.join(sorted(BREAKS))}")
    BREAKS[name]()
    return name
