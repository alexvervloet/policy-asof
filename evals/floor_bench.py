"""Where to put the distance floor, and what it costs.

Phase 4 left a hole: the coverage check asks whether *anything* was in force,
not whether anything was in force about the thing being asked. A lapsed clause
with other clauses still live gets answered from whatever three passages happen
to be nearest, and a question the handbook says nothing about gets answered the
same way.

A floor closes it, and a floor is a threshold, so it needs a curve rather than a
number somebody picked. This prints the distance of the best passage for every
gold case, on topic and off, then sweeps the threshold and reports both halves
of the tradeoff: refused when it should have, and answered when it should have.
Reporting one of those alone would flatter a system that refuses everything.

    EMBED_PROVIDER=ollama .venv/bin/python -m evals.floor_bench
"""

from __future__ import annotations

import statistics
import sys

from evals import gold
from policy_asof import db, embed, retrieve
from policy_asof.answer import AnswerOutcome
from policy_asof.clock import AsOf

# The floors to try. Cosine distance, so 0 is identical and 1 is unrelated.
SWEEP = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def main() -> int:
    corpus_rev, cases = gold.load()
    on_topic = [
        case for case in cases if case.expect_outcome is not AnswerOutcome.NO_PASSAGE_ON_TOPIC
    ]
    off_topic = [case for case in cases if case.expect_outcome is AnswerOutcome.NO_PASSAGE_ON_TOPIC]

    with db.connection() as conn:
        problems = gold.self_check(conn, cases)
        if problems:
            print("gold does not describe the store. Nothing measured.\n")
            for problem in problems:
                print(f"  {problem}")
            return 1

        def best(question: str, case_at: AsOf) -> float | None:
            query = embed.embed([question], input_type="query")[0]
            candidates = retrieve.as_of(conn, query, case_at, k=1)
            return candidates[0].distance if candidates else None

        print(f"corpus_rev {corpus_rev} · embedder {embed.model_name()}\n")

        def relaxed(question: str, case_at: AsOf) -> float | None:
            query = embed.embed([question], input_type="query")[0]
            candidates = retrieve.ignoring_valid_time(conn, query, case_at, k=1)
            return candidates[0].distance if candidates else None

        print("| case | class | best in force | best ignoring valid time | gap |")
        print("|---|---|---|---|---|")
        distances: dict[str, float] = {}
        for case in cases:
            distance = best(case.question, case.at)
            loose = relaxed(case.question, case.at)
            loose_text = "-" if loose is None else f"{loose:.4f}"
            if distance is None:
                print(f"| `{case.id}` | {case.klass} | nothing in force | {loose_text} | - |")
                continue
            distances[case.id] = distance
            gap = "-" if loose is None else f"{distance - loose:.4f}"
            print(f"| `{case.id}` | {case.klass} | {distance:.4f} | {loose_text} | {gap} |")

        answerable = [distances[c.id] for c in on_topic if c.id in distances]
        unanswerable = [distances[c.id] for c in off_topic if c.id in distances]
        print()
        print(
            f"on topic: n={len(answerable)} median {statistics.median(answerable):.4f} "
            f"max {max(answerable):.4f}"
        )
        print(
            f"off topic: n={len(unanswerable)} median {statistics.median(unanswerable):.4f} "
            f"min {min(unanswerable):.4f}"
        )
        print()

        print("| floor | off-topic refused | on-topic still answered |")
        print("|---|---|---|")
        for floor in SWEEP:
            refused = sum(1 for distance in unanswerable if distance > floor)
            answered = sum(1 for distance in answerable if distance <= floor)
            print(f"| {floor:.2f} | {refused}/{len(unanswerable)} | {answered}/{len(answerable)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
