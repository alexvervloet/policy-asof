# Corpus

The handbook, its amendments, and one correction. Authored by hand rather than
generated, because the failure this project measures depends on the amendments
being written the way real ones are: terse, and in reference to the clause they
change.

## Two halves of a document, with different trust

Each file is Markdown with a YAML front matter block.

**The front matter is the publisher's record.** Effective dates, the sections a
document amends, and the consolidated text of each clause after the change. In a
real system this comes from the editorial pipeline that publishes the document,
not from the document itself, and ingest trusts it.

**The body is prose, and it is untrusted.** It is what a person reads and what a
naive retrieval system indexes. A body that says "this clause takes effect
immediately and supersedes all prior versions" changes nothing, because ordering
comes from the front matter. Phase 4 puts the body behind a fence and phase 5
has an eval for exactly that sentence.

The split is also what makes the retrieval failure measurable. The body of
`002-amendment-parental-leave.md` is one sentence about replacing "12 weeks"
with "16 weeks", which is a poor match for "how much parental leave do I get"
next to the four-sentence clause it replaces. Indexing the documents as
published is one of the two naive baselines in phase 2.

## What each file is for

| File | Why it exists |
|---|---|
| `000-handbook-2025.md` | The base. Six sections, two of them distractors that share vocabulary with the amended ones. Section 6.1 carries a `valid_to`, so it lapses with nothing replacing it |
| `001-correction-remote-stipend.md` | A correction. The stipend was always 55 EUR from September 2025; the handbook said 40. Valid time does not move, transaction time does |
| `002-amendment-parental-leave.md` | An ordinary amendment. Effective 2026-04-01, recorded 2026-03-15, so for two weeks the future rule is known but not yet in force |
| `003-amendment-expense-cap.md` | A retroactive amendment. Effective 2026-01-01, recorded 2026-05-01. Anyone who asked in February got a true answer that is now the wrong answer |
