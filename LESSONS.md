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
