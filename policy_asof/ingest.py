"""Turn published documents into clause versions.

Both clocks move here, and they move independently. An amendment closes what we
believed and records a new belief, keeping the old rows readable rather than
overwriting them, because "what did you tell me in March" is a question this
system has to be able to answer after the fact.

Documents are applied in transaction-time order and each one is applied once,
keyed by the hash of its bytes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from policy_asof import corpus, db

# Document ids are derived from the bytes, not from the name in the front
# matter. Two reasons, and the second one cost a debugging detour.
#
# A re-ingest of an unchanged corpus writes the same rows rather than a second
# copy under new keys, which is the obvious one.
#
# And a document that is edited is a different document. Keying on the name
# assumed a name identifies one immutable text, so editing a file and
# re-ingesting collided on the primary key with no useful message. Keyed on
# content, the edit is what it actually is: a new publication, with the old row
# still on record as evidence of what was published before.
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def document_uuid(content_hash: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, content_hash)


def _current(conn: db.Conn, section: str) -> list[db.Row]:
    """What this system believes about a section right now.

    Rows with an open recorded range. Closed rows are the older beliefs, still
    readable by anyone asking what we used to say.
    """
    return conn.execute(
        """
        select id, section_key, version_no, text, valid_from, valid_to, source_document_id
        from clause_versions
        where section_key = %s and recorded_until is null
        order by valid_from
        """,
        (section,),
    ).fetchall()


def _next_version_no(conn: db.Conn, section: str) -> int:
    row = db.one(
        conn.execute(
            "select coalesce(max(version_no), 0) + 1 as next from clause_versions where section_key = %s",
            (section,),
        ).fetchall()
    )
    return int(row["next"])


def close_version(conn: db.Conn, version_id: uuid.UUID, recorded_at: datetime) -> None:
    """Stop believing a row, without deleting it. The closed row is the evidence
    of what this system used to say, so nothing here ever removes one."""
    conn.execute(
        "update clause_versions set recorded_until = %s where id = %s",
        (recorded_at, version_id),
    )


def insert_version(
    conn: db.Conn,
    *,
    section: str,
    version_no: int,
    text: str,
    valid_from: date,
    valid_to: date | None,
    recorded_at: datetime,
    source_document_id: uuid.UUID,
    supersedes: uuid.UUID | None = None,
) -> uuid.UUID:
    version_id = uuid.uuid4()
    conn.execute(
        """
        insert into clause_versions
            (id, section_key, version_no, text, valid_from, valid_to,
             recorded_at, source_document_id, supersedes)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            version_id,
            section,
            version_no,
            text,
            valid_from,
            valid_to,
            recorded_at,
            source_document_id,
            supersedes,
        ),
    )
    return version_id


def supersede_from(
    conn: db.Conn,
    *,
    section: str,
    text: str,
    effective_from: date,
    recorded_at: datetime,
    source_document_id: uuid.UUID,
) -> None:
    """An amendment: from `effective_from` onward, the clause reads differently.

    Everything the system currently believes about the section from that date
    onward is closed. A version that straddles the date is closed and its
    earlier stretch re-recorded, because that stretch is still true and still
    believed. A version entirely before the date is left alone.
    """
    version_no = _next_version_no(conn, section)
    remainders: list[tuple[str, date, uuid.UUID]] = []
    supersedes: uuid.UUID | None = None

    for row in _current(conn, section):
        if row["valid_to"] is not None and row["valid_to"] <= effective_from:
            continue
        close_version(conn, row["id"], recorded_at)
        if row["valid_from"] <= effective_from:
            supersedes = row["id"]
        if row["valid_from"] < effective_from:
            remainders.append((row["text"], row["valid_from"], row["source_document_id"]))

    # A remainder keeps the document it came from. The amendment bounded that
    # stretch, it did not write it, and attributing the old text to the new
    # document would cite the wrong source for every historical answer.
    for remainder_text, valid_from, origin in remainders:
        insert_version(
            conn,
            section=section,
            version_no=version_no,
            text=remainder_text,
            valid_from=valid_from,
            valid_to=effective_from,
            recorded_at=recorded_at,
            source_document_id=origin,
        )
        version_no += 1

    insert_version(
        conn,
        section=section,
        version_no=version_no,
        text=text,
        valid_from=effective_from,
        valid_to=None,
        recorded_at=recorded_at,
        source_document_id=source_document_id,
        supersedes=supersedes,
    )


def restate(
    conn: db.Conn,
    *,
    section: str,
    clauses: list[corpus.Clause],
    recorded_at: datetime,
    source_document_id: uuid.UUID,
) -> None:
    """A correction: the same stretch of the world, a different account of it.

    Valid time does not move. Every current row for the section is closed and
    the corrected timeline recorded in its place, so the old account stays
    readable by anyone asking what they were told at the time.
    """
    version_no = _next_version_no(conn, section)
    for row in _current(conn, section):
        close_version(conn, row["id"], recorded_at)
    for clause in clauses:
        insert_version(
            conn,
            section=section,
            version_no=version_no,
            text=clause.text,
            valid_from=clause.valid_from,
            valid_to=clause.valid_to,
            recorded_at=recorded_at,
            source_document_id=source_document_id,
        )
        version_no += 1


def already_ingested(conn: db.Conn, content_hash: str) -> bool:
    rows = conn.execute(
        "select 1 from documents where content_hash = %s", (content_hash,)
    ).fetchall()
    return len(rows) > 0


def ingest_document(conn: db.Conn, doc: corpus.Document) -> bool:
    """Apply one document. Returns False when it was already applied."""
    if already_ingested(conn, doc.content_hash):
        return False

    document_id = document_uuid(doc.content_hash)
    conn.execute(
        """
        insert into documents
            (id, kind, title, effective_from, recorded_at, content, content_hash)
        values (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            document_id,
            doc.kind,
            doc.title,
            doc.effective_from,
            doc.recorded_at,
            doc.content,
            doc.content_hash,
        ),
    )

    if doc.kind == "base":
        for clause in doc.clauses:
            insert_version(
                conn,
                section=clause.section,
                version_no=1,
                text=clause.text,
                valid_from=clause.valid_from,
                valid_to=clause.valid_to,
                recorded_at=doc.recorded_at,
                source_document_id=document_id,
            )
    elif doc.kind == "amendment":
        for clause in doc.clauses:
            supersede_from(
                conn,
                section=clause.section,
                text=clause.text,
                effective_from=clause.valid_from,
                recorded_at=doc.recorded_at,
                source_document_id=document_id,
            )
    else:
        by_section: dict[str, list[corpus.Clause]] = {}
        for clause in doc.clauses:
            by_section.setdefault(clause.section, []).append(clause)
        for section, clauses in by_section.items():
            restate(
                conn,
                section=section,
                clauses=clauses,
                recorded_at=doc.recorded_at,
                source_document_id=document_id,
            )

    return True


def ingest_all(documents: list[corpus.Document] | None = None) -> int:
    """Apply every document that has not been applied, in one transaction."""
    docs = documents if documents is not None else corpus.load()
    applied = 0
    with db.connection() as conn:
        for doc in docs:
            if ingest_document(conn, doc):
                applied += 1
    return applied
