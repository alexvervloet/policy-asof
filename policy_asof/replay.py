"""Rebuild an answer from its own row, and say what moved if it does not match.

The question this exists for is the one asked six months later, when somebody
disputes an answer and the model has been deprecated, the prompt has been edited
and the corpus has moved on. The answer text cannot be regenerated. What can be
rebuilt is the evidence: the exact passages the model was given, at the exact
instants, and a hash that proves it.

A replay that fails is a finding rather than an error, so this reports which
half diverged instead of raising.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from policy_asof import db, prompt
from policy_asof.clock import AsOf
from policy_asof.prompt import Passage


class Verdict(StrEnum):
    REPRODUCED = "reproduced"
    SYSTEM_PROMPT_CHANGED = "system-prompt-changed"
    PASSAGES_CHANGED = "passages-changed"
    NOT_REPRODUCIBLE = "not-reproducible"


@dataclass(frozen=True)
class Replay:
    answer_id: str
    verdict: Verdict
    detail: str
    rebuilt_prompt: str | None = None


def replay(conn: db.Conn, answer_id: str) -> Replay:
    rows = conn.execute(
        """
        select id, question, valid_at, known_at, corpus_rev,
               system_sha256, prompt_sha256, outcome
        from answers where id = %s
        """,
        (uuid.UUID(answer_id),),
    ).fetchall()
    if not rows:
        return Replay(answer_id, Verdict.NOT_REPRODUCIBLE, "no such answer")
    answer = rows[0]

    if str(answer["outcome"]) != "answered":
        return Replay(
            answer_id,
            Verdict.REPRODUCED,
            f"a refusal has no passages to rebuild ({answer['outcome']})",
        )

    citations = conn.execute(
        """
        select c.clause_version_id, c.section_key, c.valid_from, c.valid_to, v.text
        from answer_citations c
        join clause_versions v on v.id = c.clause_version_id
        where c.answer_id = %s
        order by c.position
        """,
        (uuid.UUID(answer_id),),
    ).fetchall()
    if not citations:
        return Replay(answer_id, Verdict.NOT_REPRODUCIBLE, "the answer cited nothing")

    passages = [
        Passage(
            clause_version_id=str(row["clause_version_id"]),
            section=str(row["section_key"]),
            text=str(row["text"]),
            valid_from=str(row["valid_from"]),
            valid_to=str(row["valid_to"]) if row["valid_to"] else None,
        )
        for row in citations
    ]
    at = AsOf(valid_at=answer["valid_at"], known_at=answer["known_at"])
    user = prompt.build(answer_id, str(answer["question"]), at, passages)

    system_now = prompt.digest_one(prompt.SYSTEM)
    if prompt.digest(prompt.SYSTEM, user) == str(answer["prompt_sha256"]):
        return Replay(answer_id, Verdict.REPRODUCED, "byte for byte", user)

    if system_now != str(answer["system_sha256"]):
        return Replay(
            answer_id,
            Verdict.SYSTEM_PROMPT_CHANGED,
            "the passages rebuild, the instructions around them have been edited since",
            user,
        )
    return Replay(
        answer_id,
        Verdict.PASSAGES_CHANGED,
        "the instructions are unchanged, so a cited clause's text has moved under it",
        user,
    )
