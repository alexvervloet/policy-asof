#!/usr/bin/env python3
"""Fail the build if anything outside `policy_asof/clock.py` reads the wall clock.

Run it with `--self-test` to watch it fail on purpose. A checker that has never
been made to fail is a checker nobody has reason to believe, and a checker that
cannot go green on a clean tree gets deleted from CI within a week.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Spelled out of band so this file does not match its own patterns.
FORBIDDEN = [
    re.compile(r"datetime\s*\.\s*" + "now" + r"\s*\("),
    re.compile(r"datetime\s*\.\s*" + "utcnow" + r"\s*\("),
    re.compile(r"date\s*\.\s*" + "today" + r"\s*\("),
    re.compile(r"time\s*\.\s*" + "time" + r"\s*\("),
]

ALLOWED = {
    Path("policy_asof/clock.py"),
    Path("scripts/check_clock_discipline.py"),
}


def violations(root: Path) -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel in ALLOWED or ".venv" in rel.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if any(pattern.search(line) for pattern in FORBIDDEN):
                found.append((rel, lineno, line.strip()))
    return found


def self_test() -> int:
    """Prove the checker can fail, on a tree built to make it fail."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        (tree / "offender.py").write_text("import datetime\nstamp = datetime.now()\n")
        found = violations(tree)
    if len(found) != 1:
        print(f"self-test failed: expected 1 violation, found {len(found)}")
        return 1
    print("self-test passed: the checker fails on a tree that deserves it")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    found = violations(ROOT)
    for rel, lineno, line in found:
        print(f"{rel}:{lineno}: reads the wall clock outside clock.py: {line}")
    if found:
        print(f"\n{len(found)} violation(s). Take the instant as an argument instead.")
        return 1
    print("clock discipline: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
