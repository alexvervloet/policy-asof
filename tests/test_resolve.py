"""Turning what somebody wrote into two instants, or refusing to.

Nothing here reads the wall clock: `now` is passed in, so these assertions mean
the same thing next April.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from policy_asof import resolve as resolve_module
from policy_asof.resolve import Resolution

resolve = resolve_module.resolve

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was the meal cap on 2026-02-01?", date(2026, 2, 1)),
        ("What was the rule on 1 March 2026?", date(2026, 3, 1)),
        ("What was the rule in March 2026?", date(2026, 3, 1)),
    ],
)
def test_a_stated_date_is_used(question: str, expected: date) -> None:
    result = resolve(question, NOW)
    assert result.outcome is Resolution.STATED
    assert result.at is not None and result.at.valid_at == expected


def test_a_month_resolves_to_its_first_day_by_convention() -> None:
    """A month is a range and the convention has to be written down somewhere,
    so it is here rather than left for a reader to infer from behaviour."""
    result = resolve("What applied in March 2026?", NOW)
    assert result.at is not None and result.at.valid_at == date(2026, 3, 1)


def test_no_date_assumes_today_and_says_so() -> None:
    result = resolve("How much parental leave do I get?", NOW)
    assert result.outcome is Resolution.ASSUMED_TODAY
    assert result.at is not None and result.at.valid_at == NOW.date()
    assert "assumed" in result.describe()


def test_asking_what_we_said_moves_the_second_clock() -> None:
    """The difference between "you were misinformed" and "the rule changed"."""
    truth = resolve("What was the meal cap on 2026-02-01?", NOW)
    recollection = resolve("What did you tell me on 2026-02-01 about the meal cap?", NOW)
    assert truth.at is not None and recollection.at is not None
    assert truth.at.valid_at == recollection.at.valid_at
    assert truth.at.known_at == NOW
    assert recollection.at.known_at.date() == date(2026, 2, 1)


@pytest.mark.parametrize(
    "question",
    [
        "How much parental leave applied in 2024?",
        "What was the stipend when I joined?",
        "What did it say back then?",
        "What was the cap last year?",
        "Was it 75 on 2026-01-01 or 90 on 2026-05-01?",
    ],
)
def test_what_cannot_be_pinned_is_refused_rather_than_guessed(question: str) -> None:
    result = resolve(question, NOW)
    assert result.outcome is Resolution.AMBIGUOUS
    assert result.at is None
    assert result.reason


@pytest.mark.layer
def test_what_cannot_be_pinned_is_refused_rather_than_defaulted() -> None:
    """Layer L1, asserted directly.

    Called through the module rather than through a name bound at import, so an
    ablation that replaces the resolver actually reaches this. The first version
    of this test held a direct reference and stayed green while the layer it
    names was removed.
    """
    assumed = resolve_module.resolve("How much parental leave do I get?", NOW)
    assert assumed.outcome is Resolution.ASSUMED_TODAY, "the assumption is allowed"

    for question in ("What was the stipend when I joined?", "What applied in 2024?"):
        refused = resolve_module.resolve(question, NOW)
        assert refused.outcome is Resolution.AMBIGUOUS, question
        assert refused.at is None
