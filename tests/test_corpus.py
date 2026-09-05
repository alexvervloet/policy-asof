"""Reading the corpus off disk."""

from __future__ import annotations

from datetime import date

import pytest

from policy_asof import corpus


def test_documents_load_in_transaction_time_order() -> None:
    """Filename order is a convenience. The store is append-only in the order
    this system learned things, and applying documents in any other order builds
    a history that never happened."""
    documents = corpus.load()
    recorded = [doc.recorded_at for doc in documents]
    assert recorded == sorted(recorded)
    assert [doc.doc_id for doc in documents] == ["H2025", "C1", "A1", "A2"]


def test_a_correction_takes_its_effective_date_from_what_it_restates() -> None:
    """A correction has no effective date of its own. It is not a change of
    policy, so valid time does not move."""
    correction = next(doc for doc in corpus.load() if doc.kind == "correction")
    assert correction.effective_from == date(2025, 1, 1)
    assert {clause.section for clause in correction.clauses} == {"5.2"}


def test_the_lapsing_section_carries_its_own_end_date() -> None:
    base = next(doc for doc in corpus.load() if doc.kind == "base")
    commuting = next(clause for clause in base.clauses if clause.section == "6.1")
    assert commuting.valid_to == date(2026, 1, 1)


def test_the_body_is_not_where_any_date_comes_from() -> None:
    """The body of the retroactive amendment says "1 January 2026" in prose. The
    date ingest uses comes from the front matter, and a document that lied in its
    body would change nothing."""
    amendment = next(doc for doc in corpus.load() if doc.doc_id == "A2")
    assert "1 January 2026" in amendment.body
    assert amendment.effective_from == date(2026, 1, 1)
    assert amendment.clauses[0].valid_from == date(2026, 1, 1)


def test_front_matter_is_required() -> None:
    with pytest.raises(ValueError, match="no front matter"):
        corpus.parse("Section 4.2 is amended.\n")
