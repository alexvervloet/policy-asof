"""The clock's contract, which the rest of the project is built on."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from policy_asof.clock import AsOf, current


def test_asof_requires_an_aware_known_at() -> None:
    """A naive timestamp compares wrongly against a stored tstzrange, silently."""
    with pytest.raises(ValueError, match="timezone aware"):
        AsOf(valid_at=date(2026, 3, 1), known_at=datetime(2026, 3, 1))


def test_asof_holds_the_two_clocks_apart() -> None:
    """'What was the rule in March' and 'what did you tell me in March' differ
    only in known_at, so the type has to be able to say both."""
    what_was_true = AsOf(valid_at=date(2026, 3, 1), known_at=datetime(2026, 9, 5, tzinfo=UTC))
    what_we_said = AsOf(valid_at=date(2026, 3, 1), known_at=datetime(2026, 3, 1, tzinfo=UTC))
    assert what_was_true.valid_at == what_we_said.valid_at
    assert what_was_true != what_we_said


def test_current_is_the_only_convenience_and_it_is_explicit() -> None:
    at = current(valid_at=date(2026, 3, 1))
    assert at.valid_at == date(2026, 3, 1)
    assert at.known_at.tzinfo is not None
