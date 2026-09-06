"""Measure the two naive baselines against the date-parameterised gold set.

Run it with a real embedder. There is no mock path: a number computed from a
hash of the text would fill this table without measuring anything.

    EMBED_PROVIDER=ollama .venv/bin/python -m evals.baseline_bench

The tables print as Markdown, for pasting into RESULTS.md with the prose that
explains them.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from evals import gold
from evals.gold import Case
from policy_asof import baselines, db, embed, read
from policy_asof.baselines import Chunk

K = 5


@dataclass
class Score:
    n: int = 0
    top1: int = 0
    recall_at_k: int = 0
    superseded_at_1: int = 0
    blended_at_k: int = 0

    def add(self, *, correct_rank: int | None, top_is_same_section: bool, blended: bool) -> None:
        self.n += 1
        if correct_rank == 0:
            self.top1 += 1
        if correct_rank is not None:
            self.recall_at_k += 1
        if correct_rank != 0 and top_is_same_section:
            self.superseded_at_1 += 1
        if blended:
            self.blended_at_k += 1

    def row(self, label: str) -> str:
        def pct(count: int) -> str:
            return f"{count}/{self.n} ({100 * count / self.n:.0f}%)" if self.n else "-"

        return (
            f"| {label} | {self.n} | {pct(self.top1)} | {pct(self.recall_at_k)} "
            f"| {pct(self.superseded_at_1)} | {pct(self.blended_at_k)} |"
        )


def _correct_rank(
    ranked: list[tuple[Chunk, float]], expected: db.Row, use_version: bool
) -> int | None:
    for position, (chunk, _) in enumerate(ranked):
        if use_version:
            if chunk.version_id == expected["id"]:
                return position
        elif (
            chunk.section == expected["section_key"]
            and chunk.source_document_id == expected["source_document_id"]
        ):
            return position
    return None


def _blended(ranked: list[tuple[Chunk, float]]) -> bool:
    seen: set[str] = set()
    for chunk, _ in ranked:
        if chunk.section in seen:
            return True
        seen.add(chunk.section)
    return False


def measure(
    conn: db.Conn, cases: list[Case], index: list[Chunk], *, use_version: bool
) -> dict[str, Score]:
    vectors = dict(
        zip(
            [chunk.chunk_id for chunk in index],
            embed.embed([chunk.text for chunk in index], input_type="document"),
            strict=True,
        )
    )
    questions = embed.embed([case.question for case in cases], input_type="query")

    scores: dict[str, Score] = {}
    for case, query in zip(cases, questions, strict=True):
        reading = read.as_of(conn, case.section, case.at)
        if reading.version is None:
            continue
        ranked = baselines.rank(index, vectors, query, K)
        scores.setdefault(case.klass, Score()).add(
            correct_rank=_correct_rank(ranked, reading.version, use_version),
            top_is_same_section=ranked[0][0].section == case.section,
            blended=_blended(ranked),
        )
    return scores


def table(title: str, scores: dict[str, Score]) -> str:
    lines = [
        f"**{title}**",
        "",
        f"| question class | n | correct @1 | correct @{K} | superseded cited @1 | blended @{K} |",
        "|---|---|---|---|---|---|",
    ]
    total = Score()
    for klass in ("current", "historical", "retroactive", "correction", "gap"):
        if klass in scores:
            lines.append(scores[klass].row(klass))
            for field in ("n", "top1", "recall_at_k", "superseded_at_1", "blended_at_k"):
                setattr(total, field, getattr(total, field) + getattr(scores[klass], field))
    lines.append(total.row("**all**"))
    return "\n".join(lines)


def margins(index: list[Chunk], section: str, question: str) -> str:
    """How much daylight there is between two versions of the same clause.

    Baseline (b) is not choosing the wrong version so much as not choosing at
    all. The versions differ by a couple of characters, so the scores differ in
    the third decimal place and the ranking is decided by noise.
    """
    query = embed.embed([question], input_type="query")[0]
    competing = [chunk for chunk in index if chunk.section == section]
    vectors = embed.embed([chunk.text for chunk in competing], input_type="document")
    scored = sorted(
        (
            (chunk, embed.cosine(query, vector))
            for chunk, vector in zip(competing, vectors, strict=True)
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    lines = [
        f"Question: *{question}*",
        "",
        "| version | first line | cosine |",
        "|---|---|---|",
    ]
    for chunk, score in scored:
        lines.append(f"| `{chunk.chunk_id}` | {chunk.text.splitlines()[0][:44]} | {score:.4f} |")
    spread = scored[0][1] - scored[-1][1]
    lines.append("")
    lines.append(f"Spread between best and worst version of section {section}: **{spread:.4f}**")
    return "\n".join(lines)


def mean_margin(index: list[Chunk], cases: list[Case]) -> str:
    """The margin baseline (b) decides on, across every scored question.

    Two versions of one clause differ by a few characters, so this is the whole
    of the evidence available to a retriever with no temporal filter.
    """
    vectors = dict(
        zip(
            [chunk.chunk_id for chunk in index],
            embed.embed([chunk.text for chunk in index], input_type="document"),
            strict=True,
        )
    )
    queries = embed.embed([case.question for case in cases], input_type="query")
    gaps: list[float] = []
    for case, query in zip(cases, queries, strict=True):
        competing = sorted(
            (
                embed.cosine(query, vectors[chunk.chunk_id])
                for chunk in index
                if chunk.section == case.section
            ),
            reverse=True,
        )
        if len(competing) > 1:
            gaps.append(competing[0] - competing[1])
    gaps.sort()
    median = gaps[len(gaps) // 2]
    return (
        f"Across {len(gaps)} questions, the gap between the best and second best version of the "
        f"target section has a median of **{median:.4f}** and a maximum of **{max(gaps):.4f}**."
    )


def headline(index: list[Chunk]) -> str:
    """The single number the corpus was authored to produce.

    An amendment is written in reference to the clause it changes, so it is
    short and it does not repeat the subject. Against the question a person
    actually asks, it loses to the clause it replaced.
    """
    question = "How much paid parental leave am I entitled to?"
    query = embed.embed([question], input_type="query")[0]
    vectors = dict(
        zip(
            [chunk.chunk_id for chunk in index],
            embed.embed([chunk.text for chunk in index], input_type="document"),
            strict=True,
        )
    )
    rows = [
        f"Question: *{question}*",
        "",
        "| chunk | what it is | cosine |",
        "|---|---|---|",
    ]
    interesting = {
        "H2025:4.2": "the superseded clause, 12 weeks",
        "A1:4.2": "the amendment that replaced it, 16 weeks",
    }
    for chunk_id, description in interesting.items():
        chunk = next(chunk for chunk in index if chunk.chunk_id == chunk_id)
        rows.append(
            f"| `{chunk_id}` | {description} | {embed.cosine(query, vectors[chunk_id]):.4f} |"
        )
        del chunk
    return "\n".join(rows)


def main() -> int:
    corpus_rev, cases = gold.load()
    scored = [case for case in cases if case.scored_for_retrieval]

    with db.connection() as conn:
        problems = gold.self_check(conn, cases)
        if problems:
            print("gold does not describe the store. Nothing measured.\n")
            for problem in problems:
                print(f"  {problem}")
            return 1

        published = baselines.published_index()
        versions = baselines.version_index(conn)

        print(f"corpus_rev {corpus_rev} · embedder {embed.model_name()} · k={K}")
        print(f"{len(scored)} scored cases, {len(cases) - len(scored)} refusal cases held back\n")
        print(f"published index: {len(published)} chunks · version index: {len(versions)} chunks\n")

        print(
            table(
                "Baseline (a): the documents as published",
                measure(conn, scored, published, use_version=False),
            )
        )
        print()
        print(
            table(
                "Baseline (b): every clause version, no temporal filter",
                measure(conn, scored, versions, use_version=True),
            )
        )
        print()
        print(headline(published))
        print()
        print(margins(versions, "4.2", "How much paid parental leave am I entitled to?"))
        print()
        print(margins(versions, "5.1", "What is the daily limit for meals when I travel for work?"))
        print()
        print(mean_margin(versions, scored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
