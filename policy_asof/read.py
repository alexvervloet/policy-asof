"""Read one clause as of one instant on each clock.

Three outcomes, never two. "No rule was in force" and "we have no record for
that date" are different answers, and a system that collapses them tells someone
they have no entitlement when the truth is that nobody wrote it down.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from policy_asof import db
from policy_asof.clock import AsOf


class Outcome(StrEnum):
    IN_FORCE = "in-force"
    NO_RULE_IN_FORCE = "no-rule-in-force"
    NO_RECORD = "no-record"


@dataclass(frozen=True)
class Reading:
    outcome: Outcome
    section: str
    at: AsOf
    version: db.Row | None = None

    @property
    def text(self) -> str | None:
        return None if self.version is None else str(self.version["text"])


def as_of(conn: db.Conn, section: str, at: AsOf) -> Reading:
    """The one version of `section` in force at `at.valid_at`, as known at `at.known_at`.

    The temporal predicate is in the query that produces the row rather than in
    a filter applied afterwards. A superseded version that is never selected
    cannot be accidentally returned, and a filter applied after the fact is a
    filter some future code path skips.
    """
    rows = conn.execute(
        """
        select id, section_key, version_no, text, valid_from, valid_to,
               recorded_at, recorded_until, source_document_id
        from clause_versions
        where section_key = %(section)s
          and valid_from <= %(valid_at)s
          and (valid_to is null or valid_to > %(valid_at)s)
          and recorded_at <= %(known_at)s
          and (recorded_until is null or recorded_until > %(known_at)s)
        """,
        {"section": section, "valid_at": at.valid_at, "known_at": at.known_at},
    ).fetchall()

    if len(rows) == 1:
        return Reading(Outcome.IN_FORCE, section, at, rows[0])
    if len(rows) > 1:
        # The exclusion constraint on clause_versions is supposed to make this
        # unreachable. If it ever fires, the store is wrong and answering from
        # an arbitrary one of the rows is the worst available response.
        raise LookupError(f"{len(rows)} versions of section {section} in force at {at}")

    known = conn.execute(
        """
        select 1
        from clause_versions
        where section_key = %(section)s
          and recorded_at <= %(known_at)s
          and (recorded_until is null or recorded_until > %(known_at)s)
        limit 1
        """,
        {"section": section, "known_at": at.known_at},
    ).fetchall()

    if known:
        return Reading(Outcome.NO_RULE_IN_FORCE, section, at)
    return Reading(Outcome.NO_RECORD, section, at)


def sections(conn: db.Conn) -> list[str]:
    rows = conn.execute(
        "select distinct section_key from clause_versions order by section_key"
    ).fetchall()
    return [str(row["section_key"]) for row in rows]


def history(conn: db.Conn, section: str) -> list[db.Row]:
    """Every version of a section, in the order the store learned them.

    Both clocks, including the closed rows, because the closed rows are the
    only evidence of what this system used to say.
    """
    return conn.execute(
        """
        select version_no, text, valid_from, valid_to, recorded_at, recorded_until
        from clause_versions
        where section_key = %s
        order by recorded_at, valid_from
        """,
        (section,),
    ).fetchall()
