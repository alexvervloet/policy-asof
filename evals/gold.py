"""The gold set, and the check that it still describes the store.

The phase 1 reader is the oracle for which version is correct, so a case names a
section and two instants rather than a version id that ingest happens to have
assigned. The strings in `must_contain` and `must_not_contain` are written by
hand and are what stops that from being circular: if the reader and the
expectations disagree, `self_check` says so and nothing downstream runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from policy_asof import db, read
from policy_asof.clock import AsOf
from policy_asof.read import Outcome

GOLD = Path(__file__).resolve().parent / "gold.yaml"


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    section: str
    valid_at: date
    known_at: datetime
    klass: str
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    expect_outcome: Outcome = Outcome.IN_FORCE

    @property
    def at(self) -> AsOf:
        return AsOf(valid_at=self.valid_at, known_at=self.known_at)

    @property
    def scored_for_retrieval(self) -> bool:
        """A case with no version in force has nothing for retrieval to find.

        Those cases are the refusal cases, measured in phase 5 against what the
        system says rather than against what it retrieves.
        """
        return self.expect_outcome is Outcome.IN_FORCE


def _instant(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"known_at must be a timestamp, got {value!r}")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(f"valid_at must be a date, got {value!r}")


def load(path: Path = GOLD) -> tuple[str, list[Case]]:
    parsed = cast("dict[str, Any]", yaml.safe_load(path.read_text()))
    cases = [
        Case(
            id=str(entry["id"]),
            question=str(entry["question"]),
            section=str(entry["section"]),
            valid_at=_day(entry["valid_at"]),
            known_at=_instant(entry["known_at"]),
            klass=str(entry["class"]),
            must_contain=tuple(entry.get("must_contain") or ()),
            must_not_contain=tuple(entry.get("must_not_contain") or ()),
            expect_outcome=Outcome(entry.get("expect_outcome", "in-force")),
        )
        for entry in cast("list[dict[str, Any]]", parsed["cases"])
    ]
    return str(parsed["corpus_rev"]), cases


def self_check(conn: db.Conn, cases: list[Case]) -> list[str]:
    """Every case, read straight out of the store. Returns the disagreements.

    This runs before any measurement. A benchmark scored against expectations
    that no longer match the corpus measures nothing, and it looks exactly like
    a benchmark that does.
    """
    problems: list[str] = []
    for case in cases:
        reading = read.as_of(conn, case.section, case.at)
        if reading.outcome is not case.expect_outcome:
            problems.append(
                f"{case.id}: expected {case.expect_outcome}, store says {reading.outcome}"
            )
            continue
        if reading.text is None:
            continue
        for needle in case.must_contain:
            if needle not in reading.text:
                problems.append(f"{case.id}: store's answer is missing {needle!r}")
        for needle in case.must_not_contain:
            if needle in reading.text:
                problems.append(f"{case.id}: store's answer contains forbidden {needle!r}")
    return problems
