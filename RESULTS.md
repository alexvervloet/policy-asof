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

## Phase 4: the answer layer

A model is in the loop now. `qwen3:8b`, run locally, temperature 0, three
passages per question, the passages fenced with a per-request nonce, every
answer written to a row that can be rebuilt afterwards.

| case | class | expected | got | outcome | correct version cited | replay |
|---|---|---|---|---|---|---|
| `parental-leave-today` | current | answered | answered | yes | yes | reproduced |
| `expense-cap-today` | current | answered | answered | yes | yes | reproduced |
| `remote-stipend-today` | current | answered | answered | yes | yes | reproduced |
| `annual-leave-today` | current | answered | answered | yes | yes | reproduced |
| `parental-leave-for-a-march-birth` | historical | answered | answered | yes | yes | reproduced |
| `remote-stipend-august-2025` | historical | answered | answered | yes | yes | reproduced |
| `equipment-allowance-2025` | historical | answered | answered | yes | yes | reproduced |
| `expense-cap-february-as-known-in-march` | retroactive | answered | answered | yes | yes | reproduced |
| `expense-cap-february-as-known-now` | retroactive | answered | answered | yes | yes | reproduced |
| `remote-stipend-october-as-known-in-january` | correction | answered | answered | yes | yes | reproduced |
| `remote-stipend-october-as-known-now` | correction | answered | answered | yes | yes | reproduced |
| `commuting-allowance-while-it-ran` | gap | answered | answered | yes | yes | reproduced |
| `commuting-allowance-after-it-expired` | gap | no-rule-in-force | **answered** | **no** | - | reproduced |
| `parental-leave-before-the-handbook` | out-of-coverage | no-rule-in-force | no-rule-in-force | yes | - | reproduced |
| `parental-leave-asked-before-anything-was-recorded` | out-of-coverage | no-record | no-record | yes | - | reproduced |

**Outcome correct: 14/15. Correct version among the citations: 12/12. Replayed
byte for byte: 15/15.**

The instants are handed to the answer layer rather than phrased in English,
deliberately. Date resolution is a separate component with its own tests, and an
eval that has to write each case as a sentence and hope the parser recovers it
is measuring the parser whatever the column headings say. An earlier version of
this table did exactly that and reported four failures that were all its own.
See LESSONS 9.

### The one real failure

`commuting-allowance-after-it-expired` asks about a train ticket allowance that
ran out on 2025-12-31 with nothing replacing it. The honest answer is that no
rule was in force. The system answered instead.

The coverage check is **global, not per topic**. It asks whether anything at all
was in force at that instant, and on 2026-06-01 plenty was, so the question goes
through to retrieval, which returns the three nearest passages that survive the
predicate. None of them is about commuting, and whether the answer is right then
depends entirely on the model noticing that and saying so. Here it did, more or
less, but that is a model doing the work of a control, which is the thing this
project keeps arguing against.

The gap between "no rule was in force anywhere" and "no rule was in force about
the thing you asked" needs a per-topic signal, and the obvious one is a distance
floor on the retrieved passages: if the nearest passage is far enough away,
there is nothing to answer from. That is a threshold with a coverage-versus-risk
curve behind it, so it is phase 5 work rather than a one-line fix, and it is on
the record as a known hole until then.

### Replay

Every answer, including every refusal, rebuilds from its own row: the stored
citations name clause versions, the stored instants name the pair of clocks, and
the rebuilt prompt hashes to what was recorded at the time.

Two hashes are stored rather than one, and that turned out to matter. The system
half of the prompt lives in code and the user half is built from the corpus, so
when a replay diverges the pair says which of them moved. There are tests for
both directions: edit the system prompt and the verdict is
`system-prompt-changed`, edit a cited clause's text in place and it is
`passages-changed`. One combined hash could only ever say that something did.

### What is not measured here

Whether the answer is *right*. This table checks that the machinery put the
correct version in front of the model and recorded enough to prove it later.
Whether the sentence that came back says 16 weeks or 12 is phase 5's job, along
with blending, the adversarial cases, and the ablation matrix.

## Phase 5: the gate, and what it is worth

Twenty-one answer cases across eight classes and nine date-resolution cases,
scored on what the system says rather than on what it was built from.

**All 30 pass.** Refused when it should have: **6/6**. Answered when it should
have: **15/15**, reported as a pair because either number alone flatters a
system that does only one of them. Replayed from their own rows: **21/21**.

A fully green gate is the least interesting sentence in this document, and the
next two sections are why.

### The distance floor, and its curve

Phase 4 left a hole: the coverage check asked whether *anything* was in force,
not whether anything was in force about the thing being asked. Closing it needs
a threshold, and a threshold needs a curve.

| floor | off-topic refused | on-topic still answered |
|---|---|---|
| 0.30 | 3/3 | 11/16 |
| 0.35 | 3/3 | 13/16 |
| 0.40 | 3/3 | 15/16 |
| 0.45 | 3/3 | 15/16 |
| **0.50** | **3/3** | **16/16** |
| 0.55 | 2/3 | 16/16 |
| 0.60 | 2/3 | 16/16 |
| 0.65 | 0/3 | 16/16 |

On-topic questions top out at 0.4534 and off-topic ones bottom out at 0.5219, so
anything in that gap works and 0.50 sits in the middle. Nineteen points, three
of them off topic. That is a small sample and the number belongs to
`nomic-embed-text`: it has to be re-derived for another embedder rather than
inherited.

The floor alone does not close the hole. The lapsed commuting allowance sits at
0.4534, under any floor that keeps the real questions answerable. A second
signal does: run the search again with the valid-time half of the predicate
dropped, and see whether a much closer passage appears **in another section**.

| case | best in force | ignoring valid time | gap |
|---|---|---|---|
| `commuting-allowance-after-it-expired` | 0.4534 | 0.3034 | **0.1499** |
| every other case | | | at or under 0.0098 |

Fifteen times the separation, so the threshold there is not delicate. The
same-section condition is the part that took a real failure to find: the hostile
amendment's clause carries forged marker text, which makes it a worse match for
the question than the clean version it replaced, and without the section check
the detector read that as a lapse and refused a question it should have
answered. The gate caught it on the first run with a real model.

### The ablation matrix

The point of the phase. Remove one layer at runtime, run both suites, and record
what notices. Everything is measured against a baseline run of the same suites
with no break.

| break removed | outcome cases newly red | layer evals newly red |
|---|---|---|
| `drop-temporal-predicate` | 7 | 5 |
| `drop-citation-storage` | 15 | 1 |
| `default-missing-date-to-today` | 4 | 1 |
| `drop-distance-floor` | 3 | 2 |
| `collapse-two-clocks` | 2 | 1 |
| `drop-coverage-check` | 1 | 1 |
| `drop-lapse-detector` | 1 | 1 |
| `drop-fence-neutralisation` | **0** | 1 |
| `fixed-fence-token` | **0** | 2 |
| `post-filter-instead-of-candidate-filter` | **0** | 2 |

Read the last three rows. **Three of the ten layers are completely invisible to
outcome testing.** Delete the neutralisation that stops a document forging a
fence marker, or replace the per-request nonce with a constant an attacker can
type, or move the temporal predicate from inside the candidate fetch to a filter
applied afterwards, and every one of the twenty-one answer cases still passes.
Only the evals written specifically to assert that those mechanisms exist go
red.

That is not a defect in the gold set. It is what defence in depth does: the
layers are redundant, so removing one leaves the others producing right answers,
and an eval suite that only asks "did the right thing happen" will keep
answering yes while the system is dismantled underneath it. A sibling project
measured the same thing from the other direction and this phase was built around
its lesson.

The first run of this matrix was worse. Five of the ten breaks turned nothing
red at all, and each one turned into a piece of work: two layer evals that did
not exist, a corpus whose adversarial content never reached the prompt, a gate
that held a name bound at import so an ablation could not reach it, and a harness
that reported a crashed run as "nothing noticed". See LESSONS 12 through 16.

### What the gate does not measure

Whether an answer is well written. Judging phrasing needs a model in the scoring
path, and a model there means a model upgrade shows up as a quality change with
nobody able to say which it was. That stays out until there is a reason to want
it, and it would run separately from the correctness number either way.

## What phase 6 has to do

An amendment falsifies answers already given. `answers` and `answer_citations`
hold everything needed to work out which: the instants, the cited version ids,
and the corpus revision. The sweep is the last mechanism, and its precision and
recall against a hand-labelled set are the last numbers.
