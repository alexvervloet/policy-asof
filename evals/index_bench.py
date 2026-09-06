"""Does the temporal predicate defeat the vector index?

The corpus this project ships is twelve rows, where an index measures nothing.
This harness builds a synthetic one at a size where it does, and asks the
question the schema was designed around: with both clocks on the same relation
as the vector, can Postgres still use an HNSW index, and what does the answer
cost in recall?

The vectors are clustered rather than uniform. Uniformly random vectors in 768
dimensions are all roughly equidistant, so the true nearest five are a lottery
and every recall number comes out near zero whatever the index does. Rows here
are a centroid plus noise, which gives the neighbourhood structure a real corpus
has and a recall figure that means something.

It writes its own table and drops it again. Nothing here touches `chunks`.

    .venv/bin/python -m evals.index_bench --rows 50000
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from pgvector import Vector

from policy_asof import db

DIMS = 768
CENTROIDS = 200
# Per-dimension noise. A unit vector has norm 1, and noise of sigma per
# dimension has norm sigma*sqrt(768), so sigma has to be well under 1/sqrt(768)
# or the noise swamps the centroid and the corpus is uniformly random again.
# Two earlier settings of this number produced recall figures near zero for
# every configuration, which is what an unstructured corpus looks like rather
# than what a bad index looks like.
NOISE = 0.02
QUERY_NOISE = 0.015

# Two probes. The first is an ordinary "what is the rule today" question, where
# most rows are still in force. The second asks about a date early enough that
# the predicate throws away all but a few percent of the table, which is where
# filtered approximate search is known to struggle: HNSW walks its graph and
# then discards what the filter rejects, so a selective filter can leave it with
# fewer than k results, or with the k worst of the ones that survived.
CURRENT = (date(2026, 6, 1), datetime(2026, 6, 1, tzinfo=UTC))
HISTORICAL = (date(2024, 2, 15), datetime(2024, 2, 15, tzinfo=UTC))

CREATE = """
create table bench_chunks (
    id             bigint      primary key,
    section_key    text        not null,
    valid_from     date        not null,
    valid_to       date,
    recorded_at    timestamptz not null,
    recorded_until timestamptz,
    embedding      vector(768) not null
)
"""

INSERT = """
insert into bench_chunks
    (id, section_key, valid_from, valid_to, recorded_at, recorded_until, embedding)
values (%(id)s, %(section)s, %(valid_from)s, %(valid_to)s, %(recorded_at)s, %(recorded_until)s, %(embedding)s)
"""

FILTERED = """
select id, embedding <=> %(query)s as distance
from bench_chunks
where valid_from <= %(valid_at)s
  and (valid_to is null or valid_to > %(valid_at)s)
  and recorded_at <= %(known_at)s
  and (recorded_until is null or recorded_until > %(known_at)s)
order by embedding <=> %(query)s
limit %(k)s
"""

UNFILTERED = """
select id, embedding <=> %(query)s as distance
from bench_chunks
order by embedding <=> %(query)s
limit %(k)s
"""

COUNT_MATCHING = """
select count(*) as n
from bench_chunks
where valid_from <= %(valid_at)s
  and (valid_to is null or valid_to > %(valid_at)s)
  and recorded_at <= %(known_at)s
  and (recorded_until is null or recorded_until > %(known_at)s)
"""

Probe = tuple[date, datetime]


@dataclass
class Result:
    label: str
    returned: float
    p50: float
    p95: float
    recall: float | None
    ratio: float | None

    def row(self) -> str:
        recall = "exact" if self.recall is None else f"{self.recall:.3f}"
        ratio = "1.000" if self.ratio is None else f"{self.ratio:.3f}"
        return (
            f"| {self.label} | {self.returned:.1f} | {self.p50:.1f} ms | {self.p95:.1f} ms "
            f"| {recall} | {ratio} |"
        )


def _unit(rng: random.Random) -> list[float]:
    values = [rng.gauss(0.0, 1.0) for _ in range(DIMS)]
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


def generate(conn: db.Conn, rows: int, rng: random.Random, centroids: list[list[float]]) -> None:
    conn.execute("drop table if exists bench_chunks")
    conn.execute(CREATE)

    epoch = date(2024, 1, 1)
    stamp_epoch = datetime(2024, 1, 1, tzinfo=UTC)

    batch: list[dict[str, object]] = []
    for identifier in range(rows):
        base = centroids[identifier % CENTROIDS]
        vector = [value + rng.gauss(0.0, NOISE) for value in base]
        valid_from = epoch.toordinal() + rng.randint(0, 700)
        recorded_days = rng.randint(0, 700)
        batch.append(
            {
                "id": identifier,
                "section": f"S{identifier % 500}",
                "valid_from": date.fromordinal(valid_from),
                "valid_to": (
                    date.fromordinal(valid_from + rng.randint(30, 500))
                    if rng.random() < 0.55
                    else None
                ),
                "recorded_at": stamp_epoch + timedelta(days=recorded_days),
                "recorded_until": (
                    stamp_epoch + timedelta(days=recorded_days + rng.randint(30, 500))
                    if rng.random() < 0.45
                    else None
                ),
                "embedding": Vector(vector),
            }
        )
        # One round trip per row is most of the wall clock at this size.
        if len(batch) == 2000:
            conn.cursor().executemany(INSERT, batch)
            batch.clear()
    if batch:
        conn.cursor().executemany(INSERT, batch)
    conn.execute("analyze bench_chunks")


def separation(conn: db.Conn, centroids: list[list[float]]) -> tuple[float, float]:
    """How clustered the generated corpus actually is.

    Mean cosine distance from a row to its own centroid, and to a different one.
    If those two numbers are close, the corpus has no neighbourhood structure,
    every recall figure comes out near zero whatever the index is doing, and the
    benchmark is measuring nothing. Checked rather than assumed, because two
    settings of NOISE got this wrong before anyone looked.
    """
    own = db.one(
        conn.execute(
            "select avg(embedding <=> %(centroid)s) as d from bench_chunks where id %% %(n)s = 0",
            {"centroid": Vector(centroids[0]), "n": CENTROIDS},
        ).fetchall()
    )["d"]
    other = db.one(
        conn.execute(
            "select avg(embedding <=> %(centroid)s) as d from bench_chunks where id %% %(n)s = 1",
            {"centroid": Vector(centroids[0]), "n": CENTROIDS},
        ).fetchall()
    )["d"]
    return float(own), float(other)


def selectivity(conn: db.Conn, probe: Probe) -> float:
    valid_at, known_at = probe
    total = db.one(conn.execute("select count(*) as n from bench_chunks").fetchall())["n"]
    matching = db.one(
        conn.execute(COUNT_MATCHING, {"valid_at": valid_at, "known_at": known_at}).fetchall()
    )["n"]
    return float(matching) / float(total)


def run(
    conn: db.Conn,
    queries: list[list[float]],
    probe: Probe,
    *,
    filtered: bool,
    k: int,
    truth: tuple[list[set[int]], list[float]] | None,
    settings: dict[str, str],
) -> tuple[Result, tuple[list[set[int]], list[float]]]:
    valid_at, known_at = probe
    sql = FILTERED if filtered else UNFILTERED
    timings: list[float] = []
    counts: list[int] = []
    got: list[set[int]] = []
    mean_distances: list[float] = []

    for query in queries:
        with conn.transaction():
            for name, value in settings.items():
                # set_config rather than a built SET statement, so nothing here
                # assembles SQL from a variable.
                conn.execute("select set_config(%s, %s, true)", (name, value))
            params = {"query": Vector(query), "k": k, "valid_at": valid_at, "known_at": known_at}
            started = time.perf_counter()
            rows = conn.execute(sql, params).fetchall()
            timings.append((time.perf_counter() - started) * 1000)
        counts.append(len(rows))
        got.append({int(row["id"]) for row in rows})
        distances = [float(row["distance"]) for row in rows]
        mean_distances.append(statistics.mean(distances) if distances else float("nan"))

    recall: float | None = None
    ratio: float | None = None
    if truth is not None:
        truth_ids, truth_distances = truth
        hits = sum(len(a & b) for a, b in zip(got, truth_ids, strict=True))
        wanted = sum(len(b) for b in truth_ids)
        recall = hits / wanted if wanted else 0.0
        # Set overlap understates badly when candidates tie: 250 rows around one
        # centroid are all near-equidistant, so picking a different five of them
        # scores zero while returning answers just as close. The ratio of mean
        # returned distance to mean exact distance says how much worse the
        # answers actually are, and 1.000 means not at all.
        pairs = [
            (mine, theirs)
            for mine, theirs in zip(mean_distances, truth_distances, strict=True)
            if theirs > 0
        ]
        ratio = statistics.mean(mine / theirs for mine, theirs in pairs) if pairs else None

    timings.sort()
    return (
        Result(
            label="",
            returned=statistics.mean(counts),
            p50=timings[len(timings) // 2],
            p95=timings[min(int(len(timings) * 0.95), len(timings) - 1)],
            recall=recall,
            ratio=ratio,
        ),
        (got, mean_distances),
    )


def plan(conn: db.Conn, probe: Probe, query: list[float], k: int) -> str:
    """The plan, with the query vector cut out of it. Printing 768 floats into a
    results document buries the two lines that matter."""
    valid_at, known_at = probe
    rows = conn.execute(
        "explain (analyze, buffers off, costs off, timing off, summary off) " + FILTERED,
        {"query": Vector(query), "valid_at": valid_at, "known_at": known_at, "k": k},
    ).fetchall()
    lines: list[str] = []
    for row in rows:
        line = str(next(iter(row.values())))
        if "::vector" in line:
            head, _, tail = line.partition("'[")
            line = f"{head}'[...768 floats...]{tail.split(']', 1)[1] if ']' in tail else ''}"
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--keep", action="store_true", help="leave the table behind")
    args = parser.parse_args()

    rng = random.Random(20260906)  # noqa: S311 - arbitrary vectors, not secrets

    with db.connection() as conn:
        db.with_vectors(conn)
        print(
            f"generating {args.rows} rows of vector({DIMS}) around {CENTROIDS} centroids ...",
            flush=True,
        )
        started = time.perf_counter()
        centroids = [_unit(rng) for _ in range(CENTROIDS)]
        generate(conn, args.rows, rng, centroids)
        print(f"generated in {time.perf_counter() - started:.1f}s\n")

        # Queries sit near a centroid, the way a real question sits near the
        # clause that answers it.
        queries = [
            [value + rng.gauss(0.0, QUERY_NOISE) for value in _unit(random.Random(seed))]  # noqa: S311
            for seed in range(args.queries)
        ]

        own, other = separation(conn, centroids)
        print(
            f"cluster check: mean cosine distance to own centroid {own:.4f}, to another {other:.4f}"
        )
        if own > other / 2:
            print(
                "\nthe generated corpus has no neighbourhood structure, so recall would be noise."
            )
            print("Lower NOISE and run again. Nothing measured.")
            conn.execute("drop table bench_chunks")
            return 1
        print()

        for name, probe in (("current", CURRENT), ("historical", HISTORICAL)):
            print(f"{name} probe: {selectivity(conn, probe):.1%} of rows survive the predicate")
        print()

        seq = {"enable_seqscan": "on", "enable_indexscan": "off"}
        results: list[tuple[str, Result]] = []
        truths: dict[str, tuple[list[set[int]], list[float]]] = {}

        for name, probe in (("current", CURRENT), ("historical", HISTORICAL)):
            exact, truth = run(
                conn, queries, probe, filtered=True, k=args.k, truth=None, settings=seq
            )
            truths[name] = truth
            results.append((f"exact scan, filtered, {name}", exact))

        unfiltered_exact, unfiltered_truth = run(
            conn, queries, CURRENT, filtered=False, k=args.k, truth=None, settings=seq
        )
        results.append(("exact scan, unfiltered", unfiltered_exact))

        print("building HNSW ...", flush=True)
        started = time.perf_counter()
        conn.execute(
            "create index bench_chunks_hnsw on bench_chunks using hnsw (embedding vector_cosine_ops)"
        )
        build_seconds = time.perf_counter() - started
        conn.execute("analyze bench_chunks")
        print(f"built in {build_seconds:.1f}s\n")

        index_on = {"enable_seqscan": "off"}
        hnsw_unfiltered, _ = run(
            conn,
            queries,
            CURRENT,
            filtered=False,
            k=args.k,
            truth=unfiltered_truth,
            settings=index_on,
        )
        results.append(("hnsw, unfiltered", hnsw_unfiltered))

        for name, probe in (("current", CURRENT), ("historical", HISTORICAL)):
            strict, _ = run(
                conn, queries, probe, filtered=True, k=args.k, truth=truths[name], settings=index_on
            )
            results.append((f"hnsw, filtered, {name}", strict))
            relaxed, _ = run(
                conn,
                queries,
                probe,
                filtered=True,
                k=args.k,
                truth=truths[name],
                settings={**index_on, "hnsw.iterative_scan": "relaxed_order"},
            )
            results.append((f"hnsw + iterative scan, filtered, {name}", relaxed))

        print(
            f"| configuration | rows returned (of {args.k}) | p50 | p95 | recall@{args.k} | distance ratio |"
        )
        print("|---|---|---|---|---|---|")
        for label, result in results:
            result.label = label
            print(result.row())

        print(f"\nHNSW build time: {build_seconds:.1f}s for {args.rows} rows\n")
        print("Plan for the filtered historical query:\n")
        print("```")
        print(plan(conn, HISTORICAL, queries[0], args.k))
        print("```")

        if not args.keep:
            conn.execute("drop table bench_chunks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
