"""Read the corpus off disk.

A document has two halves and they are trusted differently. The YAML front
matter is the publisher's record: effective dates, which sections change, and
the consolidated text of each clause afterwards. Ingest trusts it. The body is
prose that a person reads, and nothing in it decides anything, so a body
claiming to supersede all prior versions supersedes nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml

CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "documents"

Kind = Literal["base", "amendment", "correction"]


@dataclass(frozen=True)
class Clause:
    """One section's text over one stretch of valid time."""

    section: str
    text: str
    valid_from: date
    valid_to: date | None
    heading: str | None = None


@dataclass(frozen=True)
class Document:
    doc_id: str
    kind: Kind
    title: str
    effective_from: date
    recorded_at: datetime
    body: str
    content: str
    content_hash: str
    clauses: tuple[Clause, ...]


def _split(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---\n"):
        raise ValueError("document has no front matter")
    _, front, body = raw.split("---\n", 2)
    parsed: Any = yaml.safe_load(front)
    if not isinstance(parsed, dict):
        raise ValueError("front matter is not a mapping")
    # yaml.safe_load returns Any, and an isinstance check narrows it only to an
    # unparameterised dict, which the strict checker will not accept.
    return cast("dict[str, Any]", parsed), body.strip()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(f"expected a date, got {value!r}")


def _as_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"expected a timestamp, got {value!r}")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def parse(raw: str) -> Document:
    front, body = _split(raw)
    kind: Any = front["kind"]
    if kind not in ("base", "amendment", "correction"):
        raise ValueError(f"unknown document kind {kind!r}")

    recorded_at = _as_datetime(front["recorded_at"])
    clauses: list[Clause] = []

    if kind == "base":
        effective_from = _as_date(front["effective_from"])
        for entry in front["sections"]:
            clauses.append(
                Clause(
                    section=str(entry["section"]),
                    heading=entry.get("heading"),
                    text=entry["text"].strip(),
                    valid_from=_as_date(entry.get("valid_from", effective_from)),
                    valid_to=_as_date(entry["valid_to"]) if entry.get("valid_to") else None,
                )
            )
    elif kind == "amendment":
        effective_from = _as_date(front["effective_from"])
        for entry in front["amends"]:
            clauses.append(
                Clause(
                    section=str(entry["section"]),
                    text=entry["text"].strip(),
                    valid_from=effective_from,
                    valid_to=None,
                )
            )
    else:
        # A correction restates a section's whole timeline as of the moment we
        # learned better. It carries no effective date of its own, because valid
        # time does not move: only what we recorded about it does.
        for entry in front["corrects"]:
            for version in entry["versions"]:
                clauses.append(
                    Clause(
                        section=str(entry["section"]),
                        text=version["text"].strip(),
                        valid_from=_as_date(version["valid_from"]),
                        valid_to=_as_date(version["valid_to"]) if version.get("valid_to") else None,
                    )
                )
        effective_from = min(clause.valid_from for clause in clauses)

    return Document(
        doc_id=str(front["id"]),
        kind=kind,
        title=str(front["title"]),
        effective_from=effective_from,
        recorded_at=recorded_at,
        body=body,
        content=raw,
        content_hash=hashlib.sha256(raw.encode()).hexdigest(),
        clauses=tuple(clauses),
    )


def load(directory: Path = CORPUS) -> list[Document]:
    """Every document, in the order this system learned about them.

    Transaction-time order, not filename order. The store is append-only in that
    dimension, so applying them in any other order builds a history that never
    happened.
    """
    documents = [parse(path.read_text()) for path in sorted(directory.glob("*.md"))]
    return sorted(documents, key=lambda doc: doc.recorded_at)
