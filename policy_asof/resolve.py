"""Turn what the asker wrote into the two instants that decide the answer.

No model runs here. The date chooses which version of a rule applies, so it does
not go through a component that can be talked into a different answer by the
wording of a question, and it does not go through one that occasionally invents
plausible values. This is a small deterministic parser that handles what it
handles and refuses the rest by name.

Three outcomes, and the difference between the first two is recorded rather than
smoothed over:

- **stated**: the question named a date, and that is the date used.
- **assumed today**: the question named none, so the answer is about today. This
  is nearly always what the asker meant, and it is still an assumption, so it is
  carried on the answer and printed rather than left implicit.
- **ambiguous**: the question gestured at a time this parser cannot pin to an
  instant. A year is a range, not a day. "When I joined" is a fact about a
  person nobody here knows. Refusing costs a round trip; guessing costs a wrong
  answer that looks exactly like a right one.

Nothing here reads the wall clock. The caller passes the instant in, so a test
written today means the same thing next April.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from policy_asof.clock import AsOf

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)
MONTH_YEAR = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)
BARE_YEAR = re.compile(r"\b(19|20)\d{2}\b")

TODAY = re.compile(r"\b(today|right now|currently|at the moment|these days|this month)\b", re.I)

# Phrases that ask what the system said rather than what was true. They move the
# second clock, and getting them wrong is the difference between "you were
# misinformed" and "the rule changed".
RECOLLECTION = re.compile(
    r"\b(did (you|we) (tell|say)|were (you|we) saying|what did (you|we)|"
    r"according to (the|your) (handbook|record)s? (at the time|then))\b",
    re.IGNORECASE,
)

# Gestures at a time this parser will not guess at.
UNRESOLVABLE = re.compile(
    r"\b(when i (joined|started)|back then|last year|next year|a while ago|"
    r"before the (merger|reorg)|at the time|recently|soon|previously)\b",
    re.IGNORECASE,
)


class Resolution(StrEnum):
    STATED = "stated"
    ASSUMED_TODAY = "assumed-today"
    AMBIGUOUS = "ambiguous-date"


@dataclass(frozen=True)
class Resolved:
    outcome: Resolution
    at: AsOf | None
    matched: str | None = None
    reason: str | None = None

    def describe(self) -> str:
        if self.outcome is Resolution.AMBIGUOUS:
            return f"could not pin a date: {self.reason}"
        if self.at is None:
            raise ValueError("a resolved outcome must carry an instant")
        stated = "as stated in the question" if self.outcome is Resolution.STATED else "assumed"
        return f"in force on {self.at.valid_at} ({stated}), as known at {self.at.known_at:%Y-%m-%d}"


def _dates_in(question: str) -> list[tuple[date, str]]:
    found: list[tuple[date, str]] = []
    for match in ISO.finditer(question):
        found.append(
            (
                date(int(match.group(1)), int(match.group(2)), int(match.group(3))),
                match.group(0),
            )
        )
    for match in DAY_MONTH_YEAR.finditer(question):
        day_text, month_name, year_text = match.groups()
        found.append(
            (date(int(year_text), MONTHS[month_name.lower()], int(day_text)), match.group(0))
        )
    for match in MONTH_YEAR.finditer(question):
        month_name, year_text = match.groups()
        # A month is a range. The first of it is the conventional reading of
        # "in March 2026" and it is written down as a convention rather than
        # left for a reader to infer.
        found.append((date(int(year_text), MONTHS[month_name.lower()], 1), match.group(0)))
    return found


def resolve(question: str, now: datetime) -> Resolved:
    unresolvable = UNRESOLVABLE.search(question)
    if unresolvable is not None:
        return Resolved(
            Resolution.AMBIGUOUS,
            None,
            reason=f"{unresolvable.group(0)!r} is not something this system can turn into a date",
        )

    found = _dates_in(question)
    distinct = {value for value, _ in found}

    if len(distinct) > 1:
        rendered = ", ".join(sorted(str(value) for value in distinct))
        return Resolved(
            Resolution.AMBIGUOUS,
            None,
            reason=f"the question names more than one date ({rendered})",
        )

    if not found:
        bare = BARE_YEAR.search(question)
        if bare and not TODAY.search(question):
            return Resolved(
                Resolution.AMBIGUOUS,
                None,
                reason=f"{bare.group(0)} is a year, and a rule can change inside one",
            )
        return Resolved(Resolution.ASSUMED_TODAY, AsOf(valid_at=now.date(), known_at=now))

    valid_at, matched = found[0]
    # "What did you tell me in March" moves both clocks. "What was the rule in
    # March" moves only the first, and the difference is the whole project.
    known_at = (
        datetime.combine(valid_at, now.time(), tzinfo=now.tzinfo)
        if RECOLLECTION.search(question)
        else now
    )
    return Resolved(Resolution.STATED, AsOf(valid_at=valid_at, known_at=known_at), matched=matched)
