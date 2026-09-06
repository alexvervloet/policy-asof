# Results

Numbers, and what they are worth. Every figure here is reproducible with
`EMBED_PROVIDER=ollama python -m evals.baseline_bench` against corpus revision
`14d5ce14652d`, embedded with `nomic-embed-text` (768 dimensions), k=5.

## What these numbers are not

The corpus is twelve clause versions across six sections. That is small on
purpose. Nothing here measures latency, index build time, or recall at scale,
and none of these tables would say anything useful about those; a sibling
project measures retrieval at a few million vectors and finds the interesting
cliffs there. What this measures is **which version of a clause a retriever
picks**, which is a correctness question and does not need a large corpus to
answer.

One column is close to meaningless and is kept for honesty rather than removed:
`correct @5` over a nine or twelve chunk index is nearly free, and baseline (b)
scoring 100% on it says only that the right answer was among five guesses out of
twelve. The columns that carry weight are `correct @1`, `superseded cited @1`,
and the margins at the bottom.

Three of the fifteen gold cases expect a refusal rather than a version, so they
are held back from retrieval scoring and measured in phase 5 against what the
system says.

## Phase 2: the two naive baselines

Neither baseline knows what time it is. They fail differently, and both are what
somebody actually builds.

### (a) Index the documents as published

The base handbook chunked by section, plus each amendment and correction memo as
its own passage. Nine chunks.

| question class | n | correct @1 | correct @5 | superseded cited @1 | blended @5 |
|---|---|---|---|---|---|
| current | 4 | 1/4 (25%) | 2/4 (50%) | 3/4 (75%) | 3/4 (75%) |
| historical | 3 | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) | 3/3 (100%) |
| retroactive | 2 | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) | 2/2 (100%) |
| correction | 2 | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) | 2/2 (100%) |
| gap | 1 | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |
| **all** | 12 | 7/12 (58%) | 10/12 (83%) | 5/12 (42%) | 11/12 (92%) |

Read the first two rows together, because the inversion is the finding. This
baseline answers **historical** questions perfectly and **current** questions
25% of the time. It is not retrieving well and occasionally missing. It is
biased toward the base handbook in every case, and that bias happens to be right
whenever the question is about the past.

The reason is one number:

| chunk | what it is | cosine |
|---|---|---|
| `H2025:4.2` | the superseded clause, 12 weeks | 0.7885 |
| `A1:4.2` | the amendment that replaced it, 16 weeks | 0.4598 |

against *"How much paid parental leave am I entitled to?"*.

The amendment loses by 0.33, and it loses for a structural reason rather than a
fixable one. An amendment is written in reference to the clause it changes:
*"Section 4.2 is amended by replacing '12 weeks' with '16 weeks'"*. It does not
restate the subject, so it does not look like an answer to a question about the
subject. The clause it replaced is four sentences that do. Any similarity
measure that works at all will prefer the superseded text, and this is what a
system indexing published documents will confidently return.

### (b) Index every clause version, no temporal filter

Ingest's reconstructed versions, every row, including the ones the store has
stopped believing. A system with no concept of the two clocks has no reason to
treat `recorded_until` as meaning anything. Twelve chunks.

| question class | n | correct @1 | correct @5 | superseded cited @1 | blended @5 |
|---|---|---|---|---|---|
| current | 4 | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) | 4/4 (100%) |
| historical | 3 | 1/3 (33%) | 3/3 (100%) | 2/3 (67%) | 3/3 (100%) |
| retroactive | 2 | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) | 2/2 (100%) |
| correction | 2 | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) | 2/2 (100%) |
| gap | 1 | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |
| **all** | 12 | 8/12 (67%) | 12/12 (100%) | 4/12 (33%) | 12/12 (100%) |

Reconstructing the versions fixes the structural problem: every version is now
full self-contained text, so the amendment no longer competes at a disadvantage,
and `current` goes from 25% to 100%. It also inverts the bias rather than
removing it, and `historical` falls from 100% to 33%.

67% at rank 1 looks like a system that half works. It is not, and the margins
say why:

| version | first line | cosine |
|---|---|---|
| `4.2@v3` | Employees are entitled to 16 weeks of paid p | 0.7740 |
| `4.2@v1` | Employees are entitled to 12 weeks of paid p | 0.7700 |
| `4.2@v2` | Employees are entitled to 12 weeks of paid p | 0.7700 |

| version | first line | cosine |
|---|---|---|
| `5.1@v3` | Reimbursable expenses are capped at 90 EUR p | 0.7003 |
| `5.1@v1` | Reimbursable expenses are capped at 75 EUR p | 0.6997 |
| `5.1@v2` | Reimbursable expenses are capped at 75 EUR p | 0.6997 |

Across the nine questions whose section has more than one version, the gap
between the best and second best version has a **median of 0.0040 and a maximum
of 0.0101**.

Two versions of one clause differ by two characters, so they embed to nearly the
same point, and that difference is the entire evidence available to a retriever
with no temporal filter. The 67% is not a capability. It is which side of a
0.004 coin flip the wording happened to land on, and it would move with a
different embedding model, a reworded question, or an editor fixing a typo.

That is the more useful finding, because a system that is wrong 33% of the time
gets noticed. A system that is right 67% of the time for no reason gets shipped.

### Blending

`blended @5` counts answers whose top five contains more than one version of the
same clause: 92% for baseline (a) and 100% for baseline (b). Every one of those
is a context window holding two contradictory numbers for the same rule, handed
to a model with nothing to say which applies. Phase 4 measures what a model does
with that. It is not going to be good.

## Phase 3: as-of retrieval

The same twelve versions, indexed into a `chunks` relation that carries both
clocks next to the vector, retrieved with the bitemporal predicate inside the
query that produces the candidates.

**(c) as-of retrieval**

| question class | n | correct @1 | correct @5 | superseded cited @1 | blended @5 |
|---|---|---|---|---|---|
| current | 4 | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) | 0/4 (0%) |
| historical | 3 | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) | 0/3 (0%) |
| retroactive | 2 | 2/2 (100%) | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) |
| correction | 2 | 2/2 (100%) | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) |
| gap | 1 | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) |
| **all** | 12 | 12/12 (100%) | 12/12 (100%) | 0/12 (0%) | 0/12 (0%) |

### Read the 100% correctly

It is not a strong retriever. It is the same embedding model that scored 58% and
67%, and the questions are the same. What changed is that the version-choice
problem was removed from similarity's hands rather than solved by it. After the
predicate runs there is at most one version of each section left, so ranking
only has to pick the right *section*, and picking one of six sections from a
plainly worded question is not a hard problem.

`blended @5` going to 0% is worth separating from the rest, because it is not a
measurement. Two versions of one section cannot both survive the predicate, and
that is guaranteed by the exclusion constraint on `clause_versions` rather than
observed in this run. It would still be 0% with a worse embedding model or a
worse question.

So the honest summary is that phase 3 does not make retrieval better. It moves
the failure somewhere else, and the somewhere else is a smaller place: wrong
section, and questions the corpus cannot answer at all. Both are phase 4 and 5
problems, and the refusal cases held back from these tables are where they get
measured.

### The three side by side

| | (a) as published | (b) versions, unfiltered | (c) as-of |
|---|---|---|---|
| correct @1 | 58% | 67% | **100%** |
| superseded cited @1 | 42% | 33% | **0%** |
| blended @5 | 92% | 100% | **0%** |
| decided by | 0.33, structural bias | 0.0040, noise | a predicate |

The last row is the point. The first row is a consequence.

## Does the temporal predicate defeat the vector index?

Twelve rows cannot answer that, so `evals/index_bench.py` builds a synthetic
corpus at a size where it can: 50,000 rows of `vector(768)` clustered around 200
centroids, in a table with the same shape as `chunks`. Two probes, one asking
about today where 33.1% of rows survive the predicate, one asking about an early
date where **0.4%** do.

| configuration | rows returned (of 5) | p50 | p95 | recall@5 | distance ratio |
|---|---|---|---|---|---|
| exact scan, filtered, current | 5.0 | 35.7 ms | 49.0 ms | exact | 1.000 |
| exact scan, filtered, historical | 5.0 | **3.5 ms** | 4.7 ms | exact | 1.000 |
| exact scan, unfiltered | 5.0 | 148.4 ms | 158.4 ms | exact | 1.000 |
| hnsw, unfiltered | 5.0 | 17.1 ms | 18.8 ms | 0.172 | 1.020 |
| hnsw, filtered, current | 5.0 | 26.0 ms | 28.0 ms | 0.144 | 1.022 |
| hnsw + iterative scan, filtered, current | 5.0 | 25.8 ms | 43.3 ms | 0.144 | 1.022 |
| hnsw, filtered, historical | 5.0 | **37.7 ms** | 47.0 ms | 0.752 | 1.004 |
| hnsw + iterative scan, filtered, historical | 5.0 | 37.8 ms | 48.4 ms | 0.752 | 1.004 |

HNSW build time: **79.9s** for 50,000 rows, and every insert afterwards pays
graph maintenance.

**The predicate does not defeat the index.** The plan for the filtered query is
an index scan with the temporal conditions applied as it walks:

```
Limit (actual rows=5 loops=1)
  ->  Index Scan using bench_chunks_hnsw on bench_chunks (actual rows=5 loops=1)
        Order By: (embedding <=> '[...768 floats...]'::vector)
        Filter: ((valid_from <= '2024-02-15'::date) AND ((valid_to IS NULL) OR ...))
        Rows Removed by Filter: 1172
```

That is the payoff for denormalising both clocks onto the same relation as the
vector. A sibling project put its access-control filter on a joined table and
found the planner would not use the vector index at all, which is the failure
this schema was shaped to avoid.

**And the index is still the wrong choice.** Look at the historical row. The
exact scan runs in **3.5 ms** and HNSW takes **37.7 ms**, ten times slower, for
an approximate answer. The reason is the same fact from the other side: the
temporal predicate is evaluated during the scan, so only the 0.4% of rows that
survive it ever have a distance computed. The predicate is itself a very good
index, and it gets better the more historical the question is. HNSW cannot use
that, because it walks its graph first and discards what the filter rejects
afterwards, doing more work the more selective the filter is.

Even on the friendlier probe the index buys 35.7 ms against 26.0 ms, a 1.4x
saving for an approximate answer, an 80 second build, and a write penalty on
every ingest.

So: **no vector index**, and the reasoning is on the record with the numbers
that produced it. The threshold to revisit is when a question's predicate stops
being selective, which here would mean a corpus where most clauses are current
and the working set no longer fits in memory. A sibling project measures where
that cliff sits, at a few million vectors.

Two things this did not show. The known failure where a selective filter starves
an approximate search, so it returns fewer than k rows, did not reproduce: every
configuration returned all five. `hnsw.iterative_scan`, which exists to fix that,
therefore changed nothing here, and its column is in the table so that the null
result is on the record rather than absent from it.

The recall column needs one caveat. Set overlap understates badly when
candidates tie, and 250 rows around one centroid are all nearly equidistant, so
picking a different five of them scores 0.144 while returning answers that are
2% worse by distance. The distance ratio column is the honest reading: HNSW's
answers are between 0.4% and 2.2% further away than exact, which is fine. It is
the latency that disqualifies it here, not the approximation.

## What phase 4 has to handle

Retrieval now hands the model exactly one version of each relevant clause. Every
remaining way to be wrong is downstream: citing it without its date, answering
when the honest response is that no rule was in force, resolving "when I joined"
to the wrong instant, or reading an instruction out of a document body. Those
are the refusal cases and the adversarial cases, and none of them are measured
yet.
