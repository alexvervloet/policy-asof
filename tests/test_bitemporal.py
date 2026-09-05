"""The two clocks, which is the whole point of the project.

Every instant here is written down. Nothing reads the wall clock, so these
assertions mean the same thing next April as they do today.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest

from policy_asof import corpus, db, ingest, read
from policy_asof.clock import AsOf
from policy_asof.read import Outcome

FEBRUARY = date(2026, 2, 1)
BEFORE_THE_AMENDMENT = datetime(2026, 3, 1, tzinfo=UTC)
AFTER_THE_AMENDMENT = datetime(2026, 6, 1, tzinfo=UTC)


def test_a_retroactive_amendment_answers_differently_on_each_clock(ingested: db.Conn) -> None:
    """Section 5.1 was amended on 2026-05-01 with effect from 2026-01-01.

    Ask what the cap was in February and the answer depends entirely on when you
    ask. Both answers are correct. A system with one clock has to pick one and
    cannot say which it picked.
    """
    asked_in_march = read.as_of(ingested, "5.1", AsOf(FEBRUARY, BEFORE_THE_AMENDMENT))
    asked_in_june = read.as_of(ingested, "5.1", AsOf(FEBRUARY, AFTER_THE_AMENDMENT))

    assert asked_in_march.outcome is Outcome.IN_FORCE
    assert asked_in_june.outcome is Outcome.IN_FORCE
    assert asked_in_march.text is not None and "75 EUR" in asked_in_march.text
    assert asked_in_june.text is not None and "90 EUR" in asked_in_june.text


def test_a_correction_moves_only_transaction_time(ingested: db.Conn) -> None:
    """The stipend was always 55 EUR from September 2025. The handbook said 40
    until the correction landed on 2026-02-10.

    Valid time does not move here. Only the account of it does, which is what
    separates a correction from an amendment.
    """
    october = date(2025, 10, 1)
    before = read.as_of(ingested, "5.2", AsOf(october, datetime(2026, 1, 1, tzinfo=UTC)))
    after = read.as_of(ingested, "5.2", AsOf(october, datetime(2026, 3, 1, tzinfo=UTC)))

    assert before.text is not None and "40 EUR" in before.text
    assert after.text is not None and "55 EUR" in after.text

    # And the correction did not touch the period before September 2025.
    august = date(2025, 8, 1)
    unchanged = read.as_of(ingested, "5.2", AsOf(august, datetime(2026, 3, 1, tzinfo=UTC)))
    assert unchanged.text is not None and "40 EUR" in unchanged.text


def test_a_rule_can_be_known_before_it_is_in_force(ingested: db.Conn) -> None:
    """The parental leave amendment was recorded on 2026-03-15 and takes effect
    on 2026-04-01. For those two weeks the new rule is known and the old rule is
    still the one that applies."""
    known_after_recording = datetime(2026, 3, 20, tzinfo=UTC)

    march = read.as_of(ingested, "4.2", AsOf(date(2026, 3, 20), known_after_recording))
    may = read.as_of(ingested, "4.2", AsOf(date(2026, 5, 1), known_after_recording))

    assert march.text is not None and "12 weeks" in march.text
    assert may.text is not None and "16 weeks" in may.text


def test_the_answer_given_in_early_march_was_true_and_is_now_wrong(ingested: db.Conn) -> None:
    """Asked on 2026-03-01 about a leave starting in May, the honest answer was
    12 weeks, because the amendment did not exist yet. That is the answer this
    system has to be able to reproduce when someone complains in June."""
    may = date(2026, 5, 1)
    what_we_said = read.as_of(ingested, "4.2", AsOf(may, datetime(2026, 3, 1, tzinfo=UTC)))
    what_is_true = read.as_of(ingested, "4.2", AsOf(may, AFTER_THE_AMENDMENT))

    assert what_we_said.text is not None and "12 weeks" in what_we_said.text
    assert what_is_true.text is not None and "16 weeks" in what_is_true.text


def test_a_lapsed_rule_is_not_the_same_as_no_record(ingested: db.Conn) -> None:
    """Section 6.1 expired on 2025-12-31 with nothing replacing it. Telling
    someone "no rule was in force" is a different statement from "we have
    nothing written down", and only one of them is true here."""
    lapsed = read.as_of(ingested, "6.1", AsOf(date(2026, 6, 1), AFTER_THE_AMENDMENT))
    in_force = read.as_of(ingested, "6.1", AsOf(date(2025, 6, 1), AFTER_THE_AMENDMENT))
    never_written = read.as_of(ingested, "9.9", AsOf(date(2026, 6, 1), AFTER_THE_AMENDMENT))

    assert lapsed.outcome is Outcome.NO_RULE_IN_FORCE
    assert in_force.outcome is Outcome.IN_FORCE
    assert never_written.outcome is Outcome.NO_RECORD


def test_a_date_outside_coverage_still_tells_the_two_empty_answers_apart(
    ingested: db.Conn,
) -> None:
    """2024 is before the handbook existed, but the section is on record, so the
    honest answer is that no rule was in force. Asked as of a moment before the
    handbook was ingested, there is nothing on record at all."""
    before_everything = read.as_of(ingested, "4.2", AsOf(date(2024, 6, 1), AFTER_THE_AMENDMENT))
    assert before_everything.outcome is Outcome.NO_RULE_IN_FORCE

    nothing_known_yet = read.as_of(
        ingested, "4.2", AsOf(date(2025, 6, 1), datetime(2024, 1, 1, tzinfo=UTC))
    )
    assert nothing_known_yet.outcome is Outcome.NO_RECORD


def test_ingest_is_idempotent(ingested: db.Conn) -> None:
    """Re-applying the same bytes writes nothing. The key is the content hash,
    so a corpus that has not changed costs one query per document."""
    before = db.one(ingested.execute("select count(*) as n from clause_versions").fetchall())
    for doc in corpus.load():
        assert ingest.ingest_document(ingested, doc) is False
    after = db.one(ingested.execute("select count(*) as n from clause_versions").fetchall())
    assert before["n"] == after["n"]


@pytest.mark.layer
def test_two_versions_of_a_section_cannot_both_be_in_force(conn: db.Conn) -> None:
    """Layer L4, asserted directly rather than through an outcome.

    The reader raises when a query returns two rows, and every other test would
    keep passing if this constraint were dropped, because nothing else in the
    corpus produces an overlap. This is the test that goes red if someone
    removes it.
    """
    document_id = uuid.uuid4()
    conn.execute(
        """
        insert into documents (id, kind, title, effective_from, recorded_at, content, content_hash)
        values (%s, 'base', 'fixture', %s, %s, 'x', %s)
        """,
        (document_id, date(2025, 1, 1), datetime(2025, 1, 1, tzinfo=UTC), uuid.uuid4().hex),
    )
    ingest.insert_version(
        conn,
        section="7.1",
        version_no=1,
        text="first",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
        source_document_id=document_id,
    )

    with pytest.raises(psycopg.errors.ExclusionViolation), conn.transaction():
        ingest.insert_version(
            conn,
            section="7.1",
            version_no=2,
            text="overlapping",
            valid_from=date(2025, 6, 1),
            valid_to=None,
            recorded_at=datetime(2025, 6, 1, tzinfo=UTC),
            source_document_id=document_id,
        )


@pytest.mark.layer
def test_a_correction_is_allowed_to_overlap_in_valid_time(conn: db.Conn) -> None:
    """The other half of the same constraint, and the half that makes it right.

    Two rows may cover the same stretch of the world as long as the periods we
    believed them do not overlap. A constraint that forbade this would forbid
    corrections, and the project would have one clock again.
    """
    document_id = uuid.uuid4()
    conn.execute(
        """
        insert into documents (id, kind, title, effective_from, recorded_at, content, content_hash)
        values (%s, 'base', 'fixture', %s, %s, 'x', %s)
        """,
        (document_id, date(2025, 1, 1), datetime(2025, 1, 1, tzinfo=UTC), uuid.uuid4().hex),
    )
    first = ingest.insert_version(
        conn,
        section="7.2",
        version_no=1,
        text="what we said",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        recorded_at=datetime(2025, 1, 1, tzinfo=UTC),
        source_document_id=document_id,
    )
    ingest.close_version(conn, first, datetime(2026, 1, 1, tzinfo=UTC))
    ingest.insert_version(
        conn,
        section="7.2",
        version_no=2,
        text="what was true",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_document_id=document_id,
    )

    rows = read.history(conn, "7.2")
    assert [row["text"] for row in rows] == ["what we said", "what was true"]


def test_a_bounded_clause_still_cites_the_document_it_came_from(ingested: db.Conn) -> None:
    """The amendment on 2026-03-15 ended the 12 week rule. It did not write it.

    An answer about March 2026 quotes the base handbook, and saying it came from
    the amendment would misattribute every historical answer this system gives.
    """
    march = read.as_of(ingested, "4.2", AsOf(date(2026, 3, 1), AFTER_THE_AMENDMENT))
    may = read.as_of(ingested, "4.2", AsOf(date(2026, 5, 1), AFTER_THE_AMENDMENT))
    assert march.version is not None and may.version is not None

    def title(row: db.Row) -> str:
        return str(
            db.one(
                ingested.execute(
                    "select title from documents where id = %s", (row["source_document_id"],)
                ).fetchall()
            )["title"]
        )

    assert title(march.version) == "Employee Handbook 2025"
    assert title(may.version) == "Amendment 1 to the Employee Handbook 2025"
