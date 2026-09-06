# Lessons

Things that did not go the way the plan assumed, written down while the detail
was still fresh. Entries that are just "the plan worked" are omitted.

---

## 1. The auto-merge workflow could never have worked, in this repo or the one it came from

**Expected.** Copy the Dependabot auto-merge workflow from a sibling project,
which has been in place for months. Patch and minor updates merge once CI is
green, majors are left for review. Nothing to think about: it is a solved
problem with a written-down reason for every choice in it.

**What happened.** Dependabot's first run opened three pull requests within
seconds of the repo being created, all of them majors. The auto-merge workflow
ran three times and failed three times:

```
##[warning]Unexpected input(s) 'pr-number', valid inputs are
  ['alert-lookup', 'compat-lookup', 'github-token',
   'skip-commit-verification', 'skip-verification']
##[warning]Event payload missing `pull_request` key.
##[error]PR is not from Dependabot, nothing to do.
```

`dependabot/fetch-metadata` has no `pr-number` input. Not in v2, and not on
main. It reads the `pull_request` key out of the event payload, so it works
under `pull_request` and `pull_request_target` and nowhere else. The workflow
triggers on `workflow_run`, deliberately, because that is how you wait for CI
without adopting branch protection. Those two decisions are incompatible and
have always been.

The line above the call said:

```yaml
# fetch-metadata reads the PR referenced here rather than the event.
```

That comment is false. It was written to explain a parameter that the action
does not accept, and it is the reason nobody looked again.

**Why nothing caught it.** The failing job only runs when Dependabot opens a
pull request, and it only fails after CI passes on that pull request, so the red
run sits two hops from anything a person looks at. In the sibling repo the
workflow was added in the same phase as thirteen open Dependabot PRs, at least
seven of which were merged by hand while the automation was being written. The
merges happened. Nothing distinguished "the workflow merged them" from "I merged
them and the workflow failed quietly afterwards".

**Fix.** Drop the action. Dependabot writes the same metadata into the commit
message as a trailer, and `scripts/dependabot_update_type.py` reads it from
there, which needs no event payload:

```
updated-dependencies:
- dependency-name: dependabot/fetch-metadata
  update-type: version-update:semver-major
```

It classifies as `major`, `minor-or-patch`, or `unknown`, and only
`minor-or-patch` merges. `unknown` is a real outcome rather than a fallback,
because Dependabot has shipped versions that leave `update-type` off pip updates
entirely, and "I could not tell" must not merge. Four tests cover it, including
a grouped update with one major buried in it and a message with no metadata at
all. Then it was run against the three real Dependabot commits sitting in this
repo, which is the check the original never got.

**Next time.** Two things. A workflow whose failure is invisible from the
happy path needs to be watched failing at least once, on purpose, before it is
trusted, and the cheapest moment to do that is the first hour of a repo when the
bot is already filing pull requests. And porting a mechanism carries its
comments with it. The comment that explains why an option is passed is the least
likely thing in the file to be checked, because it reads as the answer to the
question a reader was about to ask.

**Verified in production, which the original never was.** Within the hour,
Dependabot rebased the open pull requests, ci ran again, and the fixed workflow
merged the minor-and-patch group on its own (`mergedBy: app/github-actions`,
one second after the auto-merge run succeeded) while leaving the pytest 9 and
mypy 2 majors open with a comment. Both halves observed, on real pull requests,
with the merge attributable to the workflow rather than to me. That attribution
is the whole point: in the sibling repo the merges and the silent failures
looked identical from the outside.

It also showed a smaller bug immediately. Every rebase runs ci again and lands
in the same step, so one pull request collected the same review note twice. The
step now checks for its own comment before posting. An automation that repeats
itself weekly gets muted, and a muted automation is a deleted one.

**Also.** knowledge-desk has the same workflow with the same false comment, so
its auto-merge has never merged anything either.

## 2. zsh's echo ate the JSON

**Expected.** Verifying the classifier against the real commits meant a loop of
`commit=$(gh api ...)` then `echo "$commit" | jq`. The workflow does the same
thing with a here-string.

**What happened.** `jq: parse error: Invalid string: control characters from
U+0000 through U+001F must be escaped`, on JSON that GitHub had just produced
and that was well formed. zsh's builtin `echo` interprets backslash escapes with
no `-e`, so every `\n` inside the commit message string became a real newline
and the JSON stopped being JSON. The loop reported `verdict=unknown` for all
three pull requests, which is the fail-closed answer and therefore looked
plausible enough to nearly accept.

**Fix.** Write the response to a file, or use `printf '%s'`. The workflow was
never affected: it runs under bash, and a here-string does not process escapes.

**Next time.** Never pipe JSON through `echo` in a shell you did not choose. The
failure is worse than an error, because a fail-closed classifier turns a mangled
input into a legitimate-looking verdict.

## 3. The type error I was suppressing was not being reported by anything

**Expected.** The migration runner reads SQL from disk and hands it to
`conn.execute`, and psycopg 3.3 types that parameter as `LiteralString` so a
query cannot be assembled from a variable that might hold request data. A
sibling project hit this and wrote down the fix: `cast(LiteralString, ...)` is
rejected as a redundant cast because mypy erases `LiteralString` in a cast
target, so the way out is a pyright-specific pragma.

**What happened.** The cast was rejected exactly as predicted. Replacing it with
`# type: ignore[arg-type]` produced:

```
policy_asof/migrate.py:36: error: Unused "type: ignore" comment  [unused-ignore]
```

Unused, because mypy does not enforce `LiteralString` at all. It erases it, so
`str` where a `LiteralString` is wanted is not an error and never was. Plain
`conn.execute(path.read_text())` type-checks clean under `strict = true`.

Which means the guarantee psycopg went to the trouble of shipping was not being
checked anywhere in this repository. CI ran ruff, mypy and pytest. The one
checker that can see the difference between a query written in the source and a
query assembled at runtime was not among them, and the project would have gone
on believing it had that protection because the sibling's lesson said the
pragma was the answer.

**Fix.** pyright in CI, `typeCheckingMode = "strict"`, the same file list mypy
gets. It then reports the line, the pragma becomes real, and the comment
explaining it is true instead of decorative.

Two things fell out of turning it on. The first run reported **54 errors on a
clean tree**, every one of them cascading from `Import "psycopg" could not be
resolved`, because pyright resolves imports against the system interpreter
rather than the project's `.venv` unless `venvPath` and `venv` say otherwise. A
checker that fails on a correct repository and cannot be made to pass gets
deleted from CI within a week, so it was run against a clean tree and required
to be silent before it went anywhere near the workflow. And with the config
naming `.venv`, CI had to build one too, which is the better arrangement anyway:
CI now installs and runs out of the same virtualenv the laptop uses instead of a
global install that resolves differently.

**Next time.** When a lesson from another project prescribes a fix, check that
the thing it works around is actually happening here. I nearly shipped a
suppression for a diagnostic no tool in this repo emits, and the suppression
would have read for the rest of the project's life as evidence that the rule was
enforced. The general form: a pragma is a claim that a checker objects. If no
checker objects, the pragma is documentation of a guarantee you do not have.

## 4. The baseline that looks fine is the one to worry about

**Expected.** Phase 2 measures a naive retriever so there is a number to beat.
The corpus was authored to make it fail in a specific way: an amendment is
written in reference to the clause it changes, so it is terse and loses on
similarity to the fat clause it replaced. Measure that, write it down, move on.

**What happened.** It failed exactly as designed, and by a wide margin. Against
*"How much paid parental leave am I entitled to?"* the superseded clause scores
**0.7885** and the amendment that replaced it scores **0.4598**. Nothing to
argue with.

The second baseline is the problem. Indexing the reconstructed versions instead
of the published documents removes the structural disadvantage, and the
aggregate goes from 58% correct at rank 1 to 67%. Class by class it swaps which
half it gets right: `current` goes from 25% to 100%, `historical` from 100% to
33%. A summary line reading "67%" describes a system that half works.

It does not half work. Two versions of one clause differ by two characters, so
they embed to nearly the same point:

```
4.2@v3  "...16 weeks..."   0.7740
4.2@v1  "...12 weeks..."   0.7700
```

Across the nine questions whose section has more than one version, the gap
between the best and second best has a median of **0.0040** and a maximum of
**0.0101**. The 67% is which side of a four-thousandths coin flip the wording
landed on. It would move with a different embedding model, a reworded question,
or an editor fixing a typo in a clause nobody was asking about.

**What this means.** The plan's phase 2 asked for one baseline and one failure,
and the failure it predicted is the honest one: large, structural, obviously
disqualifying. The baseline nobody planned for is the dangerous one, because its
aggregate number is unremarkable and its per-class numbers are only alarming if
you print them. A system that is wrong a third of the time gets noticed. A
system that is right two thirds of the time for no reason gets shipped.

**Next time.** Report the margin a decision was made by, not only whether it was
right. An accuracy figure with no measure of the evidence behind it cannot tell
a working mechanism apart from a coin that has been landing well. The per-class
split was already in the plan for a different reason and turned out to be what
made this visible at all: the aggregate hid an inversion that the two rows put
side by side.

## 5. A superseded clause was citing the amendment that ended it

**Expected.** `supersede_from` closes what the store believed and re-records the
stretch that is still true. Straightforward bookkeeping, tested, ten passing
tests on both clocks.

**What happened.** Designing the phase 2 scorer, which has to say which document
a retrieved chunk stands for, the answer for the 12 week version of section 4.2
came back as *Amendment 1*. The amendment that replaced it.

The re-recorded remainder was being inserted with the amendment's
`source_document_id`, because that is the document being processed at the time.
Every historical answer this system gave would have cited the document that
ended the rule rather than the one that wrote it, and phase 4 cites documents.

**Why nothing caught it.** Every test asserted on `text` and on the two clocks,
which were all correct. Provenance is a fourth column that nothing had needed
yet, and a column nothing reads is a column nothing checks. It would have
surfaced in phase 4 as a citation that looked plausible and was wrong, which is
the expensive place to find it.

**Fix.** The remainder carries the origin row's document. An amendment bounded
that stretch, it did not write it. There is now a test that reads the document
title for a March 2026 answer and a May 2026 answer and asserts they differ.

**Next time.** When a write path copies a field because it happens to be in
scope, ask whether that field is a fact about the operation or a fact about the
row. `recorded_at` belongs to the operation. `source_document_id` belongs to the
text, and the text is older than the operation that moved it.

## 6. A cache that quietly changed precision changed the results

**Expected.** Embeddings are cached on disk so a re-run costs nothing. Packing
each vector as 32-bit floats is half the bytes and plenty of precision for a
cosine.

**What happened.** The first smoke test of the cache compared a fresh embedding
against the cached one and they were not equal. The provider returns float64 and
the cache was handing back float32, so a benchmark run against a warm cache
produced slightly different numbers from the same benchmark run against a cold
one. With margins between competing versions of 0.004, that is not a rounding
detail.

**Fix.** Store float64, and put the format in the filename. The second half
matters more than the first: a file written in one format and read in the other
unpacks to the wrong length without raising anything, so a stale cache would
have produced vectors of 384 dimensions and a plausible looking cosine.

**Next time.** A cache is part of the measurement apparatus. Anything that
changes what comes back out of it, including precision, belongs in the key, and
the round trip deserves an equality check written the same day the cache is.

## 7. My synthetic benchmark measured nothing twice before it measured anything

**Expected.** The shipped corpus is twelve rows, so answering "does the temporal
predicate defeat the vector index" needs a synthetic one. Generate 50,000
vectors, build HNSW, compare recall and latency against an exact scan. The
generator is the boring part.

**What happened.** The first run reported `recall@5 = 0.000` for every HNSW
configuration. A perfect zero across the board is not a result, it is a broken
harness, and the cause was the vectors: uniformly random points in 768
dimensions are all roughly equidistant, so the true nearest five are a lottery
and any approximate search picks a different five with the same distances.

Fixing that by clustering the rows around 200 centroids produced recall of
0.104. Better, still meaningless, and this time the arithmetic was in the noise
scale. A unit centroid has norm 1, and per-dimension Gaussian noise of sigma has
norm `sigma * sqrt(768)`, so sigma of 0.35 gave a noise vector nine times longer
than the thing it was perturbing. The corpus was uniformly random again, wearing
a cluster's clothes.

At sigma = 0.02 the mean cosine distance from a row to its own centroid is
0.1255 and to a different one is 1.0093, which is a corpus with neighbourhoods
in it, and the numbers started meaning something.

**And the metric was still wrong.** With 250 rows around each centroid, the true
top five are near-identical, so returning a different five scores 0.172 on set
overlap while being 2% worse by distance. Set recall is the standard number and
it is the wrong one when candidates tie. The table now carries a distance ratio
next to it, and the ratio is what the conclusion rests on.

**Fix.** The generator prints the separation it achieved and refuses to report
recall when the corpus has no neighbourhood structure, which is the same shape
as the gold self-check: measure the apparatus before measuring with it.

**Next time.** A synthetic corpus is an experiment about the corpus first and
the system second. Before trusting a single figure out of one, check that the
data has the property the metric assumes, and write that check into the harness
rather than doing it once by eye. The tell here was available immediately and I
nearly explained it away: a metric that returns exactly 0.000 for every
configuration is not telling you about the configurations.

## 8. The index was fine. It was also ten times slower than not having one

**Expected.** The schema puts both clocks on the same relation as the vector,
specifically so the planner can use a vector index with the temporal predicate
in place. A sibling project found an access-control filter on a joined table
defeated its index entirely, so this was the lesson applied in advance. Measure
it, confirm the index is usable, add it.

**What happened.** The first half worked exactly as designed. The plan is an
`Index Scan using bench_chunks_hnsw` with the temporal conditions applied as a
filter while it walks, so denormalising the clocks did what it was for.

The second half inverted the conclusion. On a question about an early date,
where 0.4% of rows survive the predicate, the exact sequential scan runs in
**3.5 ms** and the HNSW scan takes **37.7 ms**. The index is ten times slower
than not having one, and it costs 80 seconds to build and a write penalty
forever.

The reason is the same fact read from the other end. Postgres evaluates the
`where` clause during the scan, so a selective temporal predicate means only a
couple of hundred rows ever have a distance computed. **The predicate is itself
an excellent index, and it gets better the more historical the question is.**
HNSW cannot use that, because it walks its graph first and discards what the
filter rejects afterwards, so it does more work the more selective the filter
gets. The two techniques are competing for the same job and the cheap one wins.

**What this means.** "Can the planner use the index with my filter in place" is
a different question from "is the index worth having", and answering the first
one well made me stop asking the second. The design decision that made the index
usable is the same decision that made it unnecessary.

**Next time.** For any filter that runs before ranking, measure the exact scan
*with the filter applied* as the baseline, not the unfiltered exact scan. The
unfiltered number here is 148 ms, and against that anything looks good. The
filtered number is 3.5 ms, and against that the index has nothing to sell.
