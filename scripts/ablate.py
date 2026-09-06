#!/usr/bin/env python3
"""Remove one layer at a time and see what notices.

Two suites are run under each break, and the difference between them is the
whole point:

- the **gate**, whose cases ask whether the right answer came out
- the **layer evals**, `pytest -m layer`, each of which asserts that one named
  mechanism is present

A break that turns nothing red is a layer with no gate; write the eval. An eval
that goes red under every break is measuring an outcome rather than a layer, and
should be counted as coverage of the outcome rather than of the mechanism.

Everything is compared against a baseline run of the same suites with no break,
so a provider that fails some cases anyway does not pollute the matrix.

    EMBED_PROVIDER=ollama ANSWER_PROVIDER=scripted .venv/bin/python -m scripts.ablate
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv" / "bin"

FAILED = re.compile(r"^\| `([^`]+)` \| [^|]+ \| \*\*(REGRESSION|gold-stale)\*\*", re.MULTILINE)
GATE_ROW = re.compile(
    r"^\| `([^`]+)` \| [^|]+ \| (pass|REGRESSION|gold-stale|\*\*REGRESSION\*\*)", re.MULTILINE
)
LAYER_FAIL = re.compile(r"^FAILED (tests/[^\s:]+)::(\S+)", re.MULTILINE)


@dataclass
class Run:
    gate_failures: set[str]
    layer_failures: set[str]
    gate_ran: bool = True
    error: str = ""


def _env(break_name: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("POLICY_ASOF_BREAK", None)
    if break_name:
        env["POLICY_ASOF_BREAK"] = break_name
    return env


def run_once(break_name: str | None) -> Run:
    env = _env(break_name)

    gate = subprocess.run(  # noqa: S603
        [str(VENV / "python"), "-m", "evals.gate"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    gate_failures = {
        case
        for case, status in GATE_ROW.findall(gate.stdout)
        if status.strip("*") in {"REGRESSION", "gold-stale"}
    }

    layer = subprocess.run(  # noqa: S603
        [str(VENV / "python"), "-m", "pytest", "-m", "layer", "-q", "--no-header"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    layer_failures = {name for _, name in LAYER_FAIL.findall(layer.stdout)}

    # A break that crashes the gate produces no case rows, which parses as "no
    # new failures" and reads as "nothing noticed this layer going away". That
    # is the worst possible way to be wrong about an ablation, so a run that did
    # not produce a full set of rows is an error rather than a result.
    scored = len(GATE_ROW.findall(gate.stdout))
    ran = gate.returncode in (0, 1) and scored > 0
    error = "" if ran else f"exit {gate.returncode}, {scored} cases scored"
    return Run(gate_failures, layer_failures, gate_ran=ran, error=error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run one break by name")
    args = parser.parse_args()

    from evals.breaks import BREAKS

    names = [args.only] if args.only else sorted(BREAKS)

    print("baseline (no break) ...", flush=True)
    baseline = run_once(None)
    print(f"  gate failures: {len(baseline.gate_failures)}")
    print(f"  layer failures: {len(baseline.layer_failures)}\n")

    if not baseline.gate_ran:
        print(f"the baseline gate did not run ({baseline.error}). Nothing to compare against.")
        return 1

    rows: list[tuple[str, str, int, set[str]]] = []
    for name in names:
        print(f"{name} ...", flush=True)
        result = run_once(name)
        new_layer = result.layer_failures - baseline.layer_failures
        if not result.gate_ran:
            rows.append((name, f"**error: {result.error}**", len(new_layer), new_layer))
            print(f"  gate ERROR ({result.error})  layer +{len(new_layer)}")
            continue
        new_gate = result.gate_failures - baseline.gate_failures
        rows.append((name, str(len(new_gate)), len(new_layer), new_layer))
        print(f"  gate +{len(new_gate)}  layer +{len(new_layer)}")

    print()
    print("| break removed | outcome cases newly red | layer evals newly red | which layer eval |")
    print("|---|---|---|---|")
    for name, gate_count, layer_count, which in rows:
        named = ", ".join(f"`{n}`" for n in sorted(which)) if which else "**none**"
        print(f"| `{name}` | {gate_count} | {layer_count} | {named} |")

    silent = [
        name for name, gate_count, layer_count, _ in rows if gate_count == "0" and layer_count == 0
    ]
    if silent:
        print()
        print("Layers nothing caught, which is the finding rather than the error:")
        for name in silent:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
