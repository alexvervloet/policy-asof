"""Measure every retriever against the date-parameterised gold set.

Two naive baselines and the as-of one, scored the same way, in one run so the
numbers are comparable. Run it with a real embedder; there is no mock path,
because a number computed from a hash of the text would fill these tables
without measuring anything.

    EMBED_PROVIDER=ollama .venv/bin/python -m evals.retrieval_bench

The tables print as Markdown, for pasting into RESULTS.md with the prose that
explains them.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from evals import gold
from evals.gold import Case
from policy_asof import baselines, db, embed, index, read, retrieve
from policy_asof.baselines import Chunk

K = 5


@dataclass(frozen=True)
class Hit:
    """One retrieved passage, reduced to what scoring needs."""

    section: str
    version_id: uuid.UUID | None = None
    source_document_id: uuid.UUID | None = None


Retriever = Callable[[Case, embed.Vector], list[Hit]]


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


def _vectors_for(index_chunks: list[Chunk]) -> dict[str, embed.Vector]:
    return dict(
        zip(
            [chunk.chunk_id for chunk in index_chunks],
            embed.embed([chunk.text for chunk in index_chunks], input_type="document"),
            strict=True,
        )
    )


def _correct_rank(hits: list[Hit], expected: db.Row, *, by_version: bool) -> int | None:
    for position, hit in enumerate(hits):
        if by_version:
            if hit.version_id == expected["id"]:
                return position
        elif (
            hit.section == expected["section_key"]
            and hit.source_document_id == expected["source_document_id"]
        ):
            return position
    return None


def _blended(hits: list[Hit]) -> bool:
    seen: set[str] = set()
    for hit in hits:
        if hit.section in seen:
            return True
        seen.add(hit.section)
    return False


def measure(
    conn: db.Conn, cases: list[Case], retriever: Retriever, *, by_version: bool
) -> dict[str, Score]:
    questions = embed.embed([case.question for case in cases], input_type="query")
    scores: dict[str, Score] = {}
    for case, query in zip(cases, questions, strict=True):
        reading = read.as_of(conn, case.section, case.at)
        if reading.version is None:
            continue
        hits = retriever(case, query)
        scores.setdefault(case.klass, Score()).add(
            correct_rank=_correct_rank(hits, reading.version, by_version=by_version),
            top_is_same_section=bool(hits) and hits[0].section == case.section,
            blended=_blended(hits),
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


def margins(index_chunks: list[Chunk], section: str, question: str) -> str:
    """How much daylight there is between two versions of the same clause.

    Baseline (b) is not choosing the wrong version so much as not choosing at
    all. The versions differ by a couple of characters, so the scores differ in
    the third decimal place and the ranking is decided by noise.
    """
    query = embed.embed([question], input_type="query")[0]
    competing = [chunk for chunk in index_chunks if chunk.section == section]
    vectors = embed.embed([chunk.text for chunk in competing], input_type="document")
    scored = sorted(
        (
            (chunk, embed.cosine(query, vector))
            for chunk, vector in zip(competing, vectors, strict=True)
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    lines = [f"Question: *{question}*", "", "| version | first line | cosine |", "|---|---|---|"]
    for chunk, score in scored:
        lines.append(f"| `{chunk.chunk_id}` | {chunk.text.splitlines()[0][:44]} | {score:.4f} |")
    lines.append("")
    lines.append(
        f"Spread between best and worst version of section {section}: "
        f"**{scored[0][1] - scored[-1][1]:.4f}**"
    )
    return "\n".join(lines)


def mean_margin(index_chunks: list[Chunk], cases: list[Case]) -> str:
    """The margin baseline (b) decides on, across every scored question."""
    vectors = _vectors_for(index_chunks)
    queries = embed.embed([case.question for case in cases], input_type="query")
    gaps: list[float] = []
    for case, query in zip(cases, queries, strict=True):
        competing = sorted(
            (
                embed.cosine(query, vectors[chunk.chunk_id])
                for chunk in index_chunks
                if chunk.section == case.section
            ),
            reverse=True,
        )
        if len(competing) > 1:
            gaps.append(competing[0] - competing[1])
    gaps.sort()
    return (
        f"Across {len(gaps)} questions, the gap between the best and second best version of the "
        f"target section has a median of **{gaps[len(gaps) // 2]:.4f}** and a maximum of "
        f"**{max(gaps):.4f}**."
    )


def headline(index_chunks: list[Chunk]) -> str:
    """The single number the corpus was authored to produce."""
    question = "How much paid parental leave am I entitled to?"
    query = embed.embed([question], input_type="query")[0]
    vectors = _vectors_for(index_chunks)
    rows = [f"Question: *{question}*", "", "| chunk | what it is | cosine |", "|---|---|---|"]
    for chunk_id, description in {
        "H2025:4.2": "the superseded clause, 12 weeks",
        "A1:4.2": "the amendment that replaced it, 16 weeks",
    }.items():
        rows.append(
            f"| `{chunk_id}` | {description} | {embed.cosine(query, vectors[chunk_id]):.4f} |"
        )
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

        written = index.build(conn)
        published = baselines.published_index()
        versions = baselines.version_index(conn)
        published_vectors = _vectors_for(published)
        version_vectors = _vectors_for(versions)

        def naive_published(case: Case, query: embed.Vector) -> list[Hit]:
            del case
            return [
                Hit(chunk.section, None, chunk.source_document_id)
                for chunk, _ in baselines.rank(published, published_vectors, query, K)
            ]

        def naive_versions(case: Case, query: embed.Vector) -> list[Hit]:
            del case
            return [
                Hit(chunk.section, chunk.version_id, chunk.source_document_id)
                for chunk, _ in baselines.rank(versions, version_vectors, query, K)
            ]

        def as_of(case: Case, query: embed.Vector) -> list[Hit]:
            return [
                Hit(candidate.section, uuid.UUID(candidate.clause_version_id))
                for candidate in retrieve.as_of(conn, query, case.at, K)
            ]

        print(f"corpus_rev {corpus_rev} · embedder {embed.model_name()} · k={K}")
        print(f"{len(scored)} scored cases, {len(cases) - len(scored)} refusal cases held back")
        print(f"{written} version(s) indexed this run\n")
        indexed = db.one(conn.execute("select count(*) as n from chunks").fetchall())["n"]
        print(
            f"published index: {len(published)} chunks · version index: {len(versions)} chunks "
            f"· chunks table: {indexed} rows\n"
        )

        print(
            table(
                "(a) the documents as published",
                measure(conn, scored, naive_published, by_version=False),
            )
        )
        print()
        print(
            table(
                "(b) every clause version, no temporal filter",
                measure(conn, scored, naive_versions, by_version=True),
            )
        )
        print()
        print(table("(c) as-of retrieval", measure(conn, scored, as_of, by_version=True)))
        print()
        print(headline(published))
        print()
        print(margins(versions, "4.2", "How much paid parental leave am I entitled to?"))
        print()
        print(mean_margin(versions, scored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
