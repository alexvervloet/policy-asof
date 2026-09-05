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
