"""Command line for the phase 1 store: ingest the corpus, read a clause.

Every command takes its instants as arguments. There is no "now" default on the
read path, because a date that was assumed rather than resolved is the whole
class of bug this project is about. `--known-at` does default to now, which is
the one safe default: the most recent belief is what an ordinary question wants.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

from policy_asof import db, ingest, read
from policy_asof.clock import AsOf, now


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def cmd_ingest(_: argparse.Namespace) -> int:
    applied = ingest.ingest_all()
    print(f"applied {applied} document(s)" if applied else "corpus already ingested")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    at = AsOf(valid_at=args.valid_at, known_at=args.known_at or now())
    with db.connection() as conn:
        reading = read.as_of(conn, args.section, at)

    print(f"section {reading.section}")
    print(f"  in force on   {at.valid_at}")
    print(f"  as known at   {at.known_at:%Y-%m-%d %H:%M %Z}")
    print(f"  outcome       {reading.outcome}")
    if reading.version is not None:
        version = reading.version
        upper = version["valid_to"] or "open"
        print(
            f"  version       v{version['version_no']}, valid [{version['valid_from']} .. {upper})"
        )
        print()
        print(reading.text)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    with db.connection() as conn:
        rows = read.history(conn, args.section)
    if not rows:
        print(f"no record of section {args.section}")
        return 1
    print(f"section {args.section}: {len(rows)} version(s), oldest belief first\n")
    for row in rows:
        valid = f"[{row['valid_from']} .. {row['valid_to'] or 'open'})"
        recorded = f"[{row['recorded_at']:%Y-%m-%d} .. {row['recorded_until'].strftime('%Y-%m-%d') if row['recorded_until'] else 'open'})"
        print(
            f"  v{row['version_no']:<3} valid {valid:<28} recorded {recorded:<26} {row['text'].splitlines()[0][:44]}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="policy-asof", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("ingest", help="apply the corpus").set_defaults(run=cmd_ingest)

    show = commands.add_parser("show", help="read one clause as of one instant")
    show.add_argument("--section", required=True)
    show.add_argument(
        "--valid-at", required=True, type=_date, help="the day the rule had to be in force"
    )
    show.add_argument("--known-at", type=_instant, help="what the system may know. Defaults to now")
    show.set_defaults(run=cmd_show)

    history = commands.add_parser("history", help="every version of a section, on both clocks")
    history.add_argument("--section", required=True)
    history.set_defaults(run=cmd_history)

    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
