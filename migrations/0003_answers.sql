-- What was said, to whom, about when, on the strength of what.
--
-- The columns are chosen so that an answer can be rebuilt from its own row six
-- months later, when the model has been deprecated, the prompt has changed and
-- the corpus has moved on. `prompt_sha256` is what makes that checkable rather
-- than merely plausible: rebuild the prompt from the stored citations and the
-- stored instants, hash it, and compare.
--
-- `corpus_rev` is here for the same reason the gold set carries it. An answer
-- that no longer reproduces is either a regression or a corpus that moved, and
-- without this column nobody can tell which.

create table answers (
    id            uuid        primary key,
    asked_at      timestamptz not null,
    question      text        not null,

    -- The two instants the answer is about, and how they were arrived at.
    valid_at      date        not null,
    known_at      timestamptz not null,
    resolution    text        not null check (resolution in ('stated', 'assumed-today', 'ambiguous-date')),

    outcome       text        not null check (outcome in ('answered', 'ambiguous-date', 'no-record', 'no-rule-in-force')),
    refusal_reason text,

    answer_text   text,
    model         text        not null,
    corpus_rev    text        not null,
    -- Two hashes, not one. The system half lives in code and the user half is
    -- built from the corpus, so when a replay diverges these say which of them
    -- moved. One combined hash can only say that something did.
    system_sha256 text        not null,
    prompt_sha256 text        not null,
    fence_token   text        not null
);

-- One row per passage the answer was allowed to draw on, bound to the version
-- and the stretch of time that version was in force. A citation without its
-- range is a citation that cannot be checked.
create table answer_citations (
    answer_id         uuid    not null references answers (id) on delete cascade,
    position          integer not null,
    clause_version_id uuid    not null references clause_versions (id),
    section_key       text    not null,
    valid_from        date    not null,
    valid_to          date,
    primary key (answer_id, position)
);

create index answers_asked_at on answers (asked_at);
create index answer_citations_version on answer_citations (clause_version_id);
