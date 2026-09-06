"""What the answer layer does with the gold set, end to end.

This measures the machinery rather than the prose: did it refuse when it should
have, answer when it should have, cite the version that was actually in force,
and can each answer be rebuilt from its own row afterwards. Phase 5 adds the
scoring of what the answer says.

Needs a real model. Run it with the local one:

    EMBED_PROVIDER=ollama ANSWER_PROVIDER=ollama .venv/bin/python -m evals.answer_bench
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime

from evals import gold
from evals.gold import Case
from policy_asof import answer, db, provider, read, replay
from policy_asof.answer import AnswerOutcome
from policy_asof.read import Outcome

# The gold set's fixed present. Nothing here reads the wall clock.
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

EXPECTED: dict[Outcome, AnswerOutcome] = {
    Outcome.IN_FORCE: AnswerOutcome.ANSWERED,
    Outcome.NO_RULE_IN_FORCE: AnswerOutcome.NO_RULE_IN_FORCE,
    Outcome.NO_RECORD: AnswerOutcome.NO_RECORD,
}


def expected_outcome(case: Case) -> AnswerOutcome:
    return EXPECTED[case.expect_outcome]


def main() -> int:
    corpus_rev, cases = gold.load()
    engine = provider.choose()

    with db.connection() as conn:
        problems = gold.self_check(conn, cases)
        if problems:
            print("gold does not describe the store. Nothing measured.\n")
            for problem in problems:
                print(f"  {problem}")
            return 1

        print(f"corpus_rev {corpus_rev} · model {engine.name} · {len(cases)} cases\n")

        rows: list[str] = []
        tally: Counter[str] = Counter()
        for case in cases:
            # The instants are handed in rather than phrased in English. An
            # earlier version of this harness translated each case into a
            # sentence and hoped the resolver recovered it, which quietly asked
            # a different question than the one the case names. Resolution is
            # measured on its own, in tests/test_resolve.py and in phase 5.
            result = answer.ask(conn, case.question, now=NOW, model=engine, k=3, at=case.at)
            answer.store(conn, result, asked_at=NOW)
            verdict = replay.replay(conn, result.id)

            want = expected_outcome(case)
            outcome_ok = result.outcome is want
            expected_version = None
            cited_ok: bool | None = None
            if want is AnswerOutcome.ANSWERED:
                reading = read.as_of(conn, case.section, case.at)
                expected_version = None if reading.version is None else str(reading.version["id"])
                cited_ok = expected_version in [c.clause_version_id for c in result.citations]

            tally["outcome_ok"] += int(outcome_ok)
            tally["n"] += 1
            if cited_ok is not None:
                tally["cited_n"] += 1
                tally["cited_ok"] += int(cited_ok)
            tally["replayed"] += int(verdict.verdict is replay.Verdict.REPRODUCED)

            rows.append(
                f"| `{case.id}` | {case.klass} | {want} | {result.outcome} "
                f"| {'yes' if outcome_ok else '**no**'} "
                f"| {'-' if cited_ok is None else ('yes' if cited_ok else '**no**')} "
                f"| {verdict.verdict} |"
            )

        print("| case | class | expected | got | outcome | correct version cited | replay |")
        print("|---|---|---|---|---|---|---|")
        for row in rows:
            print(row)

        print()
        print(f"Outcome correct: **{tally['outcome_ok']}/{tally['n']}**")
        print(f"Correct version among the citations: **{tally['cited_ok']}/{tally['cited_n']}**")
        print(f"Replayed byte for byte: **{tally['replayed']}/{tally['n']}**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
