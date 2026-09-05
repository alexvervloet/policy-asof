"""The two naive retrievers this project exists to beat.

Neither knows what time it is. They fail for different reasons and both are
what somebody actually builds:

(a) `published_index` indexes the documents as published, so an amendment is a
    terse memo competing on similarity with the four-sentence clause it
    replaces.
(b) `version_index` indexes every reconstructed clause version, so retrieval has
    every version of the answer and nothing to choose between them with.

Each chunk carries the version it stands for. Those labels are for the scorer.
The retriever never sees them, and neither baseline could use them if it did,
because using them is the thing that makes a system not naive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from policy_asof import corpus, db, embed, ingest


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    section: str
    text: str
    source_document_id: uuid.UUID
    version_id: uuid.UUID | None = None


def published_index() -> list[Chunk]:
    """Baseline (a): the documents, chunked the way a person would chunk them.

    A handbook splits by section. An amendment memo is one short passage, and
    the section it belongs to comes from the publisher's record rather than from
    anything in the prose.
    """
    chunks: list[Chunk] = []
    for doc in corpus.load():
        document_id = ingest.document_uuid(doc.doc_id)
        if doc.kind == "base":
            for clause in doc.clauses:
                heading = f"{clause.section} {clause.heading}\n" if clause.heading else ""
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc.doc_id}:{clause.section}",
                        section=clause.section,
                        text=f"{heading}{clause.text}",
                        source_document_id=document_id,
                    )
                )
        else:
            for section in dict.fromkeys(clause.section for clause in doc.clauses):
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc.doc_id}:{section}",
                        section=section,
                        text=f"{doc.title}\n{doc.body}",
                        source_document_id=document_id,
                    )
                )
    return chunks


def version_index(conn: db.Conn) -> list[Chunk]:
    """Baseline (b): every row in the version table, with no filter at all.

    Including the rows the store has stopped believing, because a system with no
    concept of the two clocks has no reason to treat `recorded_until` as
    meaning anything.
    """
    rows = conn.execute(
        """
        select id, section_key, text, source_document_id, version_no
        from clause_versions
        order by section_key, version_no
        """
    ).fetchall()
    return [
        Chunk(
            chunk_id=f"{row['section_key']}@v{row['version_no']}",
            section=str(row["section_key"]),
            text=str(row["text"]),
            source_document_id=row["source_document_id"],
            version_id=row["id"],
        )
        for row in rows
    ]


def rank(
    index: list[Chunk], vectors: dict[str, embed.Vector], query: embed.Vector, k: int
) -> list[tuple[Chunk, float]]:
    scored = [(chunk, embed.cosine(query, vectors[chunk.chunk_id])) for chunk in index]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
