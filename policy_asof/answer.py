"""Answer one question, and record enough to defend the answer later.

The order is deliberate. Resolve the instants first, because a question whose
date cannot be pinned is refused before a model is called and before anything is
retrieved. Then retrieve as of those instants, so the model never sees a version
that was not in force. Then check coverage, so the two empty answers stay
distinct. Only then does anything reach a model.

Four outcomes, and three of them are refusals with their own reason code:

- `answered`
- `ambiguous-date`: the question gestured at a time nobody can pin
- `no-record`: nothing was known to this system at that instant
- `no-rule-in-force`: something was known, and none of it applied on that day

Collapsing the last two into "I don't know" is the failure this project keeps
coming back to. One means the archive is incomplete. The other means the person
genuinely had no entitlement, and saying it when the truth is the first one is
the more expensive mistake by a distance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from policy_asof import db, embed, fence, prompt, provider, read, retrieve
from policy_asof.clock import AsOf
from policy_asof.prompt import Passage
from policy_asof.read import Outcome
from policy_asof.resolve import Resolution, resolve


class AnswerOutcome(StrEnum):
    ANSWERED = "answered"
    AMBIGUOUS_DATE = "ambiguous-date"
    NO_RECORD = "no-record"
    NO_RULE_IN_FORCE = "no-rule-in-force"


@dataclass(frozen=True)
class Citation:
    clause_version_id: str
    section: str
    valid_from: str
    valid_to: str | None


@dataclass(frozen=True)
class Answer:
    id: str
    question: str
    outcome: AnswerOutcome
    resolution: Resolution
    at: AsOf | None
    text: str | None = None
    refusal_reason: str | None = None
    citations: tuple[Citation, ...] = ()
    model: str = "none"
    corpus_rev: str = ""
    system_sha256: str = ""
    prompt_sha256: str = ""
    fence_token: str = ""
    system: str = field(default="", repr=False)
    user: str = field(default="", repr=False)


def corpus_revision(conn: db.Conn) -> str:
    """A hash of what is in the store, so an answer records what it was drawn from."""
    row = db.one(
        conn.execute(
            "select coalesce(md5(string_agg(content_hash, ',' order by recorded_at)), '') as rev from documents"
        ).fetchall()
    )
    return str(row["rev"])[:12]


def _passages(candidates: list[retrieve.Candidate], conn: db.Conn) -> list[Passage]:
    rows = {
        str(row["id"]): row
        for row in conn.execute(
            "select id, valid_from, valid_to from clause_versions where id = any(%s)",
            ([uuid.UUID(candidate.clause_version_id) for candidate in candidates],),
        ).fetchall()
    }
    passages: list[Passage] = []
    for candidate in candidates:
        row = rows[candidate.clause_version_id]
        passages.append(
            Passage(
                clause_version_id=candidate.clause_version_id,
                section=candidate.section,
                text=candidate.text,
                valid_from=str(row["valid_from"]),
                valid_to=str(row["valid_to"]) if row["valid_to"] else None,
            )
        )
    return passages


def ask(
    conn: db.Conn,
    question: str,
    *,
    now: datetime,
    request_id: str | None = None,
    k: int = 3,
    model: provider.Provider | None = None,
) -> Answer:
    answer_id = request_id or str(uuid.uuid4())
    resolved = resolve(question, now)
    revision = corpus_revision(conn)

    if resolved.outcome is Resolution.AMBIGUOUS or resolved.at is None:
        return Answer(
            id=answer_id,
            question=question,
            outcome=AnswerOutcome.AMBIGUOUS_DATE,
            resolution=Resolution.AMBIGUOUS,
            at=None,
            refusal_reason=resolved.reason,
            corpus_rev=revision,
            fence_token=fence.token(answer_id),
        )

    at = resolved.at
    coverage = read.coverage(conn, at)
    if coverage is not Outcome.IN_FORCE:
        return Answer(
            id=answer_id,
            question=question,
            outcome=(
                AnswerOutcome.NO_RECORD
                if coverage is Outcome.NO_RECORD
                else AnswerOutcome.NO_RULE_IN_FORCE
            ),
            resolution=resolved.outcome,
            at=at,
            refusal_reason=(
                f"nothing was on record at {at.known_at:%Y-%m-%d}"
                if coverage is Outcome.NO_RECORD
                else f"no rule was in force on {at.valid_at}"
            ),
            corpus_rev=revision,
            fence_token=fence.token(answer_id),
        )

    query = embed.embed([question], input_type="query")[0]
    candidates = retrieve.as_of(conn, query, at, k=k)
    if not candidates:
        return Answer(
            id=answer_id,
            question=question,
            outcome=AnswerOutcome.NO_RULE_IN_FORCE,
            resolution=resolved.outcome,
            at=at,
            refusal_reason=f"no passage was in force on {at.valid_at}",
            corpus_rev=revision,
            fence_token=fence.token(answer_id),
        )

    passages = _passages(candidates, conn)
    user = prompt.build(answer_id, question, at, passages)
    engine = model or provider.choose()
    text = engine.complete(prompt.SYSTEM, user)

    return Answer(
        id=answer_id,
        question=question,
        outcome=AnswerOutcome.ANSWERED,
        resolution=resolved.outcome,
        at=at,
        text=text,
        citations=tuple(
            Citation(
                clause_version_id=passage.clause_version_id,
                section=passage.section,
                valid_from=passage.valid_from,
                valid_to=passage.valid_to,
            )
            for passage in passages
        ),
        model=engine.name,
        corpus_rev=revision,
        system_sha256=prompt.digest_one(prompt.SYSTEM),
        prompt_sha256=prompt.digest(prompt.SYSTEM, user),
        fence_token=fence.token(answer_id),
        system=prompt.SYSTEM,
        user=user,
    )


def store(conn: db.Conn, answer: Answer, *, asked_at: datetime) -> None:
    conn.execute(
        """
        insert into answers
            (id, asked_at, question, valid_at, known_at, resolution, outcome,
             refusal_reason, answer_text, model, corpus_rev, system_sha256,
             prompt_sha256, fence_token)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid.UUID(answer.id),
            asked_at,
            answer.question,
            answer.at.valid_at if answer.at else asked_at.date(),
            answer.at.known_at if answer.at else asked_at,
            answer.resolution,
            answer.outcome,
            answer.refusal_reason,
            answer.text,
            answer.model,
            answer.corpus_rev,
            answer.system_sha256,
            answer.prompt_sha256,
            answer.fence_token,
        ),
    )
    for position, citation in enumerate(answer.citations):
        conn.execute(
            """
            insert into answer_citations
                (answer_id, position, clause_version_id, section_key, valid_from, valid_to)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.UUID(answer.id),
                position,
                uuid.UUID(citation.clause_version_id),
                citation.section,
                citation.valid_from,
                citation.valid_to,
            ),
        )
