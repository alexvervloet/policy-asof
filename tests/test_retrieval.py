"""As-of retrieval, with a stubbed embedder.

Nothing here calls a model. Each clause version gets a deterministic vector so
the ranking is a fact rather than a measurement, and the measurement lives in
`evals/retrieval_bench.py`, which needs a real embedder and does not run in CI.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from policy_asof import db, embed, index, retrieve
from policy_asof.clock import AsOf

NOW = datetime(2026, 6, 1, tzinfo=UTC)
DIMS = 768


def _vector(seed: int) -> list[float]:
    """A unit vector pointing at one axis, so similarity is decidable by hand."""
    vector = [0.0] * DIMS
    vector[seed % DIMS] = 1.0
    return vector


@pytest.fixture
def indexed(ingested: db.Conn, monkeypatch: pytest.MonkeyPatch) -> Iterator[db.Conn]:
    """Every version indexed, with the text deciding the vector.

    Versions of section 4.2 all point at axis 1, so the temporal predicate is
    the only thing that can tell them apart. That is the point: with a stub
    that makes every version of a clause identical, any correct answer has to
    come from the clocks.
    """

    def fake(texts: list[str], input_type: str | None = None) -> list[list[float]]:
        del input_type
        return [_vector(1 if "parental" in text else 2) for text in texts]

    monkeypatch.setattr(embed, "embed", fake)
    monkeypatch.setattr(embed, "model_name", lambda: "stub-768")
    index.build(ingested)
    yield ingested


def test_the_same_question_retrieves_a_different_version_on_each_clock(
    indexed: db.Conn,
) -> None:
    query = _vector(1)
    march = retrieve.as_of(indexed, query, AsOf(date(2026, 3, 1), NOW), k=1)
    may = retrieve.as_of(indexed, query, AsOf(date(2026, 5, 1), NOW), k=1)

    assert "12 weeks" in march[0].text
    assert "16 weeks" in may[0].text


def test_the_retroactive_amendment_is_invisible_before_it_was_recorded(
    indexed: db.Conn,
) -> None:
    """Section 5.1 was amended on 2026-05-01 with effect from 2026-01-01. A
    question asked in March cannot retrieve a row the store did not have."""
    query = _vector(2)
    at = AsOf(date(2026, 2, 1), datetime(2026, 3, 1, tzinfo=UTC))
    texts = [candidate.text for candidate in retrieve.as_of(indexed, query, at, k=5)]
    assert any("75 EUR" in text for text in texts)
    assert not any("90 EUR" in text for text in texts)


@pytest.mark.layer
def test_the_candidate_fetch_filters_by_both_clocks(indexed: db.Conn) -> None:
    """Layer L2, asserted directly rather than through an outcome.

    Every version of section 4.2 has the same vector here, so similarity cannot
    choose between them. At most one survives the predicate, and that is a
    property of the query rather than of the ranking. Remove the predicate and
    this goes red while the outcome evals above may not.
    """
    query = _vector(1)
    at = AsOf(date(2026, 3, 1), NOW)

    filtered = retrieve.as_of(indexed, query, at, k=10)
    unfiltered = retrieve.unfiltered(indexed, query, k=10)

    assert len([c for c in filtered if c.section == "4.2"]) == 1
    assert len([c for c in unfiltered if c.section == "4.2"]) == 3


@pytest.mark.layer
def test_blending_is_impossible_rather_than_unlikely(indexed: db.Conn) -> None:
    """Two versions of one section cannot both come back, at any instant.

    Not because ranking prefers one, but because the exclusion constraint makes
    two rows in force at one instant unstorable. The guarantee is in the schema;
    this is the test that says so.
    """
    for valid_at in (date(2025, 6, 1), date(2026, 3, 1), date(2026, 6, 1)):
        candidates = retrieve.as_of(indexed, _vector(1), AsOf(valid_at, NOW), k=10)
        sections = [candidate.section for candidate in candidates]
        assert len(sections) == len(set(sections)), f"blended at {valid_at}"


def test_indexing_is_idempotent_and_keyed_by_model(indexed: db.Conn) -> None:
    before = db.one(indexed.execute("select count(*) as n from chunks").fetchall())["n"]
    assert index.build(indexed) == 0
    after = db.one(indexed.execute("select count(*) as n from chunks").fetchall())["n"]
    assert before == after


@pytest.mark.layer
def test_a_vector_of_the_wrong_length_is_refused(
    ingested: db.Conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schema's dimension is the embedding model's, and changing model means
    a migration. Saying so loudly beats a Postgres error nobody can place."""

    def wrong(texts: list[str], input_type: str | None = None) -> list[list[float]]:
        del input_type
        return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(embed, "embed", wrong)
    monkeypatch.setattr(embed, "model_name", lambda: "stub-384")
    with pytest.raises(ValueError, match="means a migration"):
        index.build(ingested)


def test_the_declared_dimension_is_read_from_the_catalogue(ingested: db.Conn) -> None:
    assert index.declared_dimension(ingested) == DIMS
