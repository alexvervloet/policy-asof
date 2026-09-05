"""The gold set, and the check that guards it.

None of this needs an embedder. The measurement does, and the measurement is a
developer harness rather than something CI runs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from evals import gold
from policy_asof import db
from policy_asof.read import Outcome

CLASSES = {"current", "historical", "retroactive", "correction", "gap", "out-of-coverage"}


def test_every_case_has_a_known_class_and_two_instants() -> None:
    _, cases = gold.load()
    assert cases
    for case in cases:
        assert case.klass in CLASSES, case.id
        assert case.known_at.tzinfo is not None, case.id
        assert isinstance(case.valid_at, date), case.id


def test_the_same_question_appears_at_more_than_one_instant() -> None:
    """The whole point of the set. A question with one answer is not a case
    this project is about."""
    _, cases = gold.load()
    questions: dict[str, int] = {}
    for case in cases:
        questions[case.question] = questions.get(case.question, 0) + 1
    assert [question for question, count in questions.items() if count > 1]


def test_refusal_cases_are_held_back_from_retrieval_scoring() -> None:
    _, cases = gold.load()
    refusals = [case for case in cases if not case.scored_for_retrieval]
    assert {case.expect_outcome for case in refusals} == {
        Outcome.NO_RULE_IN_FORCE,
        Outcome.NO_RECORD,
    }


def test_gold_agrees_with_the_store(ingested: db.Conn) -> None:
    _, cases = gold.load()
    assert gold.self_check(ingested, cases) == []


def test_the_self_check_can_be_made_to_fail(ingested: db.Conn) -> None:
    """A checker that has never been made to fail is a checker nobody has a
    reason to believe, and this one is what stops a benchmark from being scored
    against expectations that no longer describe the corpus."""
    wrong_outcome = gold.Case(
        id="invented",
        question="?",
        section="4.2",
        valid_at=date(2026, 6, 1),
        known_at=datetime(2026, 6, 1, tzinfo=UTC),
        klass="current",
        must_contain=("47 weeks",),
    )
    problems = gold.self_check(ingested, [wrong_outcome])
    assert len(problems) == 1
    assert "47 weeks" in problems[0]


def test_a_case_naming_a_section_that_does_not_exist_is_caught(ingested: db.Conn) -> None:
    missing = gold.Case(
        id="invented",
        question="?",
        section="99.9",
        valid_at=date(2026, 6, 1),
        known_at=datetime(2026, 6, 1, tzinfo=UTC),
        klass="current",
    )
    problems = gold.self_check(ingested, [missing])
    assert problems and "no-record" in problems[0]


def test_an_unknown_outcome_in_the_file_is_refused() -> None:
    with pytest.raises(ValueError, match="not a valid Outcome"):
        gold.Case(
            id="x",
            question="?",
            section="4.2",
            valid_at=date(2026, 6, 1),
            known_at=datetime(2026, 6, 1, tzinfo=UTC),
            klass="current",
            expect_outcome=Outcome("something-else"),
        )
