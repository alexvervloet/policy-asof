# policy-asof

Point-in-time question answering over a policy corpus that keeps being amended.

## The sentence this exists for

*The employee asked what the parental leave policy is. The correct answer
depends on whether she is asking about today, about the leave that started in
March, or about what we told her in March.*

## The problem

Most retrieval systems, including the ones in the rest of this portfolio, treat
the corpus as a thing that is true now. Ask a handbook assistant about parental
leave and it finds the passage that best matches the words in your question.
That passage is whichever version of the clause reads most like an answer, which
is usually the superseded one, because amendments are terse and written in
reference to the thing they change.

So the failure is not that retrieval breaks. Retrieval works exactly as
designed, returns a high similarity score, and the answer is false.

## Two clocks

Valid time is when a rule was in force. Transaction time is when this system
learned about it. They come apart constantly:

- A retroactive amendment adopted in May, effective from January, means "what
  was the rule in February" has one answer today and had a different one in
  February. Both were true when given.
- A correction changes what we know without changing what was true.
- A lapsed rule leaves a period with no rule at all, which is a different answer
  from having no record of that period.

Every version row carries both ranges, and Postgres refuses to store two
versions of one clause in force at the same instant on both clocks.

## What it is measuring

The deliverable is `RESULTS.md`, not the application:

- naive semantic retrieval against as-of retrieval, per question class, so the
  gap on historical and retroactive questions is a number
- blend rate, meaning answers that cite two versions of the same clause
- accuracy of turning a phrase like "when I joined" into an instant
- precision and recall of the sweep that decides which past answers a new
  amendment falsified
- an ablation matrix: remove each layer, run the whole eval gate, and record
  what turns red. A layer nothing catches is a layer with no gate

## Status

Phase 1. The store answers point-in-time questions from the command line. There
is no retrieval and no model yet: you name the section, and the two clocks
decide which version you get.

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -e .
docker compose up -d
.venv/bin/python -m policy_asof.migrate
.venv/bin/python -m policy_asof.cli ingest
```

Postgres listens on 5438 so it cannot collide with a sibling project's database.

Then ask the same question twice, moving only the clock that says what the
system is allowed to know:

```console
$ policy-asof show --section 5.1 --valid-at 2026-02-01 --known-at 2026-03-01
  outcome       in-force
  version       v1, valid [2025-01-01 .. open)
  Reimbursable expenses are capped at 75 EUR per day ...

$ policy-asof show --section 5.1 --valid-at 2026-02-01
  outcome       in-force
  version       v3, valid [2026-01-01 .. open)
  Reimbursable expenses are capped at 90 EUR per day ...
```

Both answers are correct. The cap was 75 EUR as far as anyone knew in March, and
an amendment recorded on 1 May moved it to 90 EUR with effect from 1 January. A
system with one clock has to pick one of those and cannot tell you which.

`policy-asof history --section 5.2` prints every version of a clause on both
clocks, including the rows the system has stopped believing, which are the only
evidence of what it used to say.

## Licence

MIT.
