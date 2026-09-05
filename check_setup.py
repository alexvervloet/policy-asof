#!/usr/bin/env python3
"""Preflight for a fresh clone. Reports what is missing, changes nothing.

It is a convenience for a person. The application provisions itself through
migrations, so nothing at runtime may depend on this file having been run.
"""

from __future__ import annotations

import os
import sys

DSN = os.environ.get("POLICY_ASOF_DSN", "postgresql://policy:policy@localhost:5438/policy_asof")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'ok' if ok else 'XX'}] {label}{f': {detail}' if detail else ''}")
    return ok


def main() -> int:
    print("policy-asof setup check\n")
    results: list[bool] = []

    results.append(
        check(
            "python >= 3.13",
            sys.version_info >= (3, 13),
            f"{sys.version_info.major}.{sys.version_info.minor}",
        )
    )

    try:
        import psycopg

        results.append(check("psycopg importable", True, psycopg.__version__))
    except ImportError as exc:
        results.append(check("psycopg importable", False, str(exc)))
        psycopg = None  # type: ignore[assignment]

    if psycopg is not None:
        try:
            with psycopg.connect(DSN, connect_timeout=3) as conn:
                version = conn.execute("select version()").fetchone()
                results.append(check("postgres reachable on 5438", True, str(version)[:40]))
                extensions = {
                    row[0]
                    for row in conn.execute(
                        "select extname from pg_extension where extname in ('vector','btree_gist')"
                    )
                }
                results.append(
                    check(
                        "extensions installed",
                        extensions == {"vector", "btree_gist"},
                        ", ".join(sorted(extensions)) or "none; run the migrations",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - a preflight reports, it does not raise
            results.append(check("postgres reachable on 5438", False, str(exc).strip()[:80]))

    print()
    if all(results):
        print("all green")
        return 0
    print("not ready. Start the database with: docker compose up -d")
    return 1


if __name__ == "__main__":
    sys.exit(main())
