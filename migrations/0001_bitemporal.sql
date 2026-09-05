-- The two clocks.
--
-- valid time     (valid_from, valid_to):        when the rule was in force
-- transaction time (recorded_at, recorded_until): when this system knew it
--
-- Both are half-open, [from, to). A null upper bound means still open. Every
-- interesting case in this project is one where the two disagree: a retroactive
-- amendment moves valid time into the past, and a correction moves transaction
-- time while leaving valid time alone.

create table documents (
    id               uuid primary key,
    kind             text        not null check (kind in ('base', 'amendment', 'correction')),
    title            text        not null,
    -- What the publisher says. Untrusted: it is parsed out of the document by
    -- ingest, and a document does not get to assert its own precedence.
    effective_from   date        not null,
    effective_to     date,
    -- When this system learned about the document.
    recorded_at      timestamptz not null,
    content          text        not null,
    content_hash     text        not null,
    unique (content_hash)
);

create table clause_versions (
    id                 uuid        primary key,
    -- Stable across versions. Section 4.2 is one clause with a history, not
    -- three unrelated passages that happen to share a number.
    section_key        text        not null,
    version_no         integer     not null,
    text               text        not null,

    valid_from         date        not null,
    valid_to           date,
    recorded_at        timestamptz not null,
    recorded_until     timestamptz,

    source_document_id uuid        not null references documents (id),
    supersedes         uuid        references clause_versions (id),

    unique (section_key, version_no),
    check (valid_to is null or valid_to > valid_from),
    check (recorded_until is null or recorded_until > recorded_at)
);

-- Two versions of one section cannot both be in force at one instant on both
-- clocks at once. Rows may overlap in valid time as long as their recorded
-- ranges do not, which is exactly what a correction is: same period of the
-- world, two different things we believed about it.
--
-- This is layer L4. It is here rather than in application code because a
-- constraint the database enforces survives a bug in the code that writes.
alter table clause_versions
    add constraint clause_versions_no_overlap
    exclude using gist (
        section_key                                   with =,
        daterange(valid_from, valid_to, '[)')         with &&,
        tstzrange(recorded_at, recorded_until, '[)')  with &&
    );

create index clause_versions_asof
    on clause_versions (section_key, valid_from, recorded_at);
