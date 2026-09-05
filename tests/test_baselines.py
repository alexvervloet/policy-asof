"""The naive indexes and the ranking, with a stub embedder.

Nothing here calls a model. The vectors are hand-written so the ranking is a
fact rather than a measurement, and the measurement lives in
`evals/baseline_bench.py`, which refuses to run without a real embedder.
"""

from __future__ import annotations

import pytest

from policy_asof import baselines, db, embed, ingest


def test_the_published_index_holds_the_documents_as_published() -> None:
    index = baselines.published_index()
    ids = {chunk.chunk_id for chunk in index}
    assert "H2025:4.2" in ids, "the base handbook, chunked by section"
    assert "A1:4.2" in ids, "the amendment memo, as its own passage"
    # The memo is the terse thing a person publishes, not the consolidated text.
    memo = next(chunk for chunk in index if chunk.chunk_id == "A1:4.2")
    assert "16 weeks" in memo.text
    assert len(memo.text) < len(next(c for c in index if c.chunk_id == "H2025:4.2").text)


def test_the_version_index_holds_every_version_including_the_closed_ones(
    ingested: db.Conn,
) -> None:
    """A retriever with no concept of the two clocks has no reason to treat
    `recorded_until` as meaning anything, so the naive index keeps rows the
    store has stopped believing."""
    index = baselines.version_index(ingested)
    closed = db.one(
        ingested.execute(
            "select count(*) as n from clause_versions where recorded_until is not null"
        ).fetchall()
    )
    total = db.one(ingested.execute("select count(*) as n from clause_versions").fetchall())
    assert closed["n"] > 0
    assert len(index) == total["n"]


def test_ranking_orders_by_cosine_and_cuts_at_k() -> None:
    index = [
        baselines.Chunk("a", "4.2", "", ingest.document_uuid("H2025")),
        baselines.Chunk("b", "4.2", "", ingest.document_uuid("A1")),
        baselines.Chunk("c", "5.1", "", ingest.document_uuid("H2025")),
    ]
    vectors = {"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [0.7071, 0.7071]}
    ranked = baselines.rank(index, vectors, [1.0, 0.0], 2)
    assert [chunk.chunk_id for chunk, _ in ranked] == ["a", "c"]
    assert ranked[0][1] == pytest.approx(1.0)


def test_cosine_is_the_ordinary_one() -> None:
    assert embed.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert embed.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert embed.cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert embed.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


@pytest.mark.layer
def test_there_is_no_mock_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer, asserted directly.

    Everywhere else in this project a keyless fallback is the right call. Here
    it would fill a results table with numbers derived from a hash, which is not
    a smaller version of the truth. If someone adds a fallback, this goes red.
    """
    monkeypatch.setattr(embed, "PROVIDER", "definitely-not-a-provider")
    monkeypatch.setattr(embed, "CACHE", embed.CACHE / "nonexistent-for-this-test")
    with pytest.raises(embed.EmbedderUnavailable, match="unknown EMBED_PROVIDER"):
        embed.embed(["anything at all"])


@pytest.mark.layer
def test_an_unreachable_embedder_raises_rather_than_degrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embed, "PROVIDER", "ollama")
    monkeypatch.setattr(embed, "OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(embed, "CACHE", embed.CACHE / "nonexistent-for-this-test")
    with pytest.raises(embed.EmbedderUnavailable):
        embed.embed(["anything at all"])


@pytest.mark.layer
def test_a_non_http_embedder_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "PROVIDER", "ollama")
    monkeypatch.setattr(embed, "OLLAMA_URL", "file:///etc")
    monkeypatch.setattr(embed, "CACHE", embed.CACHE / "nonexistent-for-this-test")
    with pytest.raises(embed.EmbedderUnavailable, match="non-http"):
        embed.embed(["anything at all"])
