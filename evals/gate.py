"""The merge gate: what the system says, scored against the gold set.

Two kinds of failure, and only one of them is a bug:

- **REGRESSION**: the case fails and the corpus revision matches the one it was
  authored against. The code moved. This fails the gate.
- **GOLD_STALE**: the case fails and the corpus revision has moved. The world
  moved. This fails a separate gate that a person clears by re-authoring the
  case, printing the diff, and putting it in the commit message. Pasting in
  whatever the system currently says is how a real regression hides behind a
  corpus edit.

Nothing here reads the wall clock. The gold set names its own present, so a
suite that passes today means the same thing next April, and a case only goes
stale when the corpus changes rather than when the calendar does.

    EMBED_PROVIDER=ollama ANSWER_PROVIDER=ollama .venv/bin/python -m evals.gate
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from evals import breaks, gold
from evals.gold import Case, ResolutionCase
from policy_asof import answer, db, provider, replay
from policy_asof import resolve as resolve_module

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class Status(StrEnum):
    PASSED = "pass"
    REGRESSION = "REGRESSION"
    GOLD_STALE = "gold-stale"


@dataclass
class Outcome:
    case_id: str
    klass: str
    status: Status
    detail: str
    answer_id: str | None = None


def _score(case: Case, result: answer.Answer) -> list[str]:
    """Everything wrong with this answer, as a list rather than the first thing."""
    faults: list[str] = []
    if result.outcome is not case.expect_outcome:
        faults.append(f"outcome {result.outcome}, wanted {case.expect_outcome}")
        return faults

    text = result.text or ""
    for needle in case.must_contain:
        if needle not in text:
            faults.append(f"missing {needle!r}")
    for needle in case.must_not_contain:
        if needle in text:
            # The blend detector. An answer that says "12 weeks (16 from April)"
            # contains the right string and has still wandered off the instant
            # it was asked about.
            faults.append(f"contains forbidden {needle!r}")
    return faults


def run_answers(
    conn: db.Conn, cases: list[Case], engine: provider.Provider, *, stale: bool
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        result = answer.ask(conn, case.question, now=NOW, model=engine, k=3, at=case.at)
        answer.store(conn, result, asked_at=NOW)
        faults = _score(case, result)
        if result.outcome is answer.AnswerOutcome.ANSWERED:
            verdict = replay.replay(conn, result.id)
            if verdict.verdict is not replay.Verdict.REPRODUCED:
                faults.append(f"does not replay: {verdict.verdict}")
        outcomes.append(
            Outcome(
                case.id,
                case.klass,
                Status.PASSED
                if not faults
                else (Status.GOLD_STALE if stale else Status.REGRESSION),
                "; ".join(faults) or str(result.outcome),
                answer_id=result.id,
            )
        )
    return outcomes


def run_resolution(cases: list[ResolutionCase], *, stale: bool) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        # Through the module, not a from-import. A name bound at import time
        # cannot be replaced by an ablation, and the matrix said so.
        got = resolve_module.resolve(case.question, NOW)
        faults: list[str] = []
        if str(got.outcome) != case.expect:
            faults.append(f"outcome {got.outcome}, wanted {case.expect}")
        elif got.at is not None:
            if case.valid_at is not None and got.at.valid_at != case.valid_at:
                faults.append(f"valid_at {got.at.valid_at}, wanted {case.valid_at}")
            moved = got.at.known_at < NOW
            if moved is not case.moves_known_at:
                faults.append(
                    f"known_at {'moved' if moved else 'stayed'}, "
                    f"wanted it to {'move' if case.moves_known_at else 'stay'}"
                )
        status = (
            Status.PASSED if not faults else (Status.GOLD_STALE if stale else Status.REGRESSION)
        )
        outcomes.append(
            Outcome(case.id, "resolution", status, "; ".join(faults) or str(got.outcome))
        )
    return outcomes


def table(title: str, outcomes: list[Outcome]) -> str:
    lines = [f"**{title}**", "", "| case | class | status | detail |", "|---|---|---|---|"]
    for outcome in outcomes:
        marker = "**" if outcome.status is Status.REGRESSION else ""
        lines.append(
            f"| `{outcome.case_id}` | {outcome.klass} | {marker}{outcome.status}{marker} "
            f"| {outcome.detail} |"
        )
    return "\n".join(lines)


def by_class(outcomes: list[Outcome]) -> str:
    counts: dict[str, Counter[str]] = {}
    for outcome in outcomes:
        counts.setdefault(outcome.klass, Counter())[str(outcome.status)] += 1
    lines = ["| class | pass | fail |", "|---|---|---|"]
    for klass in sorted(counts):
        tally = counts[klass]
        total = sum(tally.values())
        lines.append(f"| {klass} | {tally['pass']}/{total} | {total - tally['pass']} |")
    return "\n".join(lines)


def refusal_pair(cases: list[Case], outcomes: list[Outcome]) -> str:
    """Two numbers, always. One of them hides a system that refuses everything."""
    wanted = {case.id: case.expect_outcome for case in cases}
    should_refuse = [c for c in cases if c.expect_outcome is not answer.AnswerOutcome.ANSWERED]
    should_answer = [c for c in cases if c.expect_outcome is answer.AnswerOutcome.ANSWERED]
    passed = {outcome.case_id for outcome in outcomes if outcome.status is Status.PASSED}
    del wanted
    return (
        f"Refused when it should have: **{sum(1 for c in should_refuse if c.id in passed)}"
        f"/{len(should_refuse)}**. "
        f"Answered when it should have: **{sum(1 for c in should_answer if c.id in passed)}"
        f"/{len(should_answer)}**."
    )


def main() -> int:
    broken = breaks.apply_from_env()
    corpus_rev, cases = gold.load()
    resolution_cases = gold.load_resolution()
    engine = provider.choose()

    with db.connection() as conn:
        actual_rev = answer.corpus_revision(conn)
        stale = actual_rev != corpus_rev

        problems = gold.self_check(conn, cases)
        if problems:
            print("gold does not describe the store. Nothing measured.\n")
            for problem in problems:
                print(f"  {problem}")
            return 1

        print(f"corpus_rev {actual_rev} · model {engine.name} · {len(cases)} answer cases")
        if broken:
            print(f"BREAK APPLIED: {broken}")
        if stale:
            print(
                f"\n  NOTE: gold was authored against {corpus_rev}, the store is at "
                f"{actual_rev}.\n  Failures below are reported as gold-stale rather than "
                "regressions.\n"
            )
        print()

        answers = run_answers(conn, cases, engine, stale=stale)
        resolutions = run_resolution(resolution_cases, stale=stale)
        every = answers + resolutions

        print(table("Answers", answers))
        print()
        print(table("Date resolution", resolutions))
        print()
        print(by_class(every))
        print()
        print(refusal_pair(cases, answers))
        print()

        replayed = sum(
            1
            for outcome in answers
            if outcome.answer_id
            and replay.replay(conn, outcome.answer_id).verdict is replay.Verdict.REPRODUCED
        )
        print(f"Replayed from their own rows: **{replayed}/{len(answers)}**")

        regressions = [o for o in every if o.status is Status.REGRESSION]
        stale_cases = [o for o in every if o.status is Status.GOLD_STALE]
        print()
        print(f"REGRESSION: {len(regressions)} · gold-stale: {len(stale_cases)}")
        return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
