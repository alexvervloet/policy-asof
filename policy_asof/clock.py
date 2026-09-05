"""The only module in this project allowed to read the wall clock.

Everything else takes the instant it needs as an argument. An eval suite about
time that drifts with time is unusable within a quarter, so the tests pin both
clocks and `scripts/check_clock_discipline.py` fails the build if anything else
reaches for the current time.

The other reason this module is small and deliberate: a missing date is not
today. `AsOf` has no defaults, so code that does not know which instant it is
answering for cannot get one by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class AsOf:
    """The pair of instants that decides which version of a rule applies.

    valid_at: the day the question is about, the day the rule had to be in force.
    known_at: the moment the answer may draw on. Set it to now for "what was the
        rule in March", and to March for "what did you tell me in March".
    """

    valid_at: date
    known_at: datetime

    def __post_init__(self) -> None:
        if self.known_at.tzinfo is None:
            raise ValueError("known_at must be timezone aware")


def now() -> datetime:
    """Wall clock, in UTC. One of two functions in the project that may do this."""
    return datetime.now(UTC)


def today() -> date:
    """Wall clock date, in UTC. The other one."""
    return now().date()


def current(valid_at: date | None = None) -> AsOf:
    """The everyday case: what is the rule today, using everything we know now.

    `valid_at` is still explicit at the call site when it is not today, because
    the whole class of bug this project is about starts with a date that was
    assumed rather than resolved.
    """
    return AsOf(valid_at=valid_at if valid_at is not None else today(), known_at=now())
