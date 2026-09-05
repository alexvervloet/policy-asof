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

## What phase 3 has to beat

| | baseline (a) | baseline (b) | as-of retrieval |
|---|---|---|---|
| correct @1 | 58% | 67% | phase 3 |
| superseded cited @1 | 42% | 33% | phase 3 |
| blended @5 | 92% | 100% | phase 3 |
| decided by a margin of | 0.33, structural | 0.0040, noise | phase 3 |

The target is not a better number in the first row. It is the last row: a
decision made by a predicate that is true or false rather than by four
thousandths of a cosine.
