"""Merge-gating evals.

Two kinds live here and they are labelled with pytest markers, because the
distinction is the point: an `eval` asks whether the right answer came out, a
`layer` eval asserts that one named mechanism is present. A system with several
defences keeps producing right answers after two of them are deleted, so the
outcome evals cannot see a layer go.
"""
