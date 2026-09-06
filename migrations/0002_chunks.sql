-- The retrieval relation.
--
-- Validity is denormalised from clause_versions on purpose. The temporal
-- predicate and the vector have to live on the same relation, because a
-- predicate that decides which rows survive, evaluated on a joined table,
-- defeats the vector index: the planner cannot push it below the scan and ends
-- up filtering after ranking rather than before. A sibling project measured
-- that costing an index entirely, so this schema starts where that one ended up.
--
-- The dimension is the embedding model's, and it is not configurable from the
-- environment. Changing model means a migration. `policy_asof.index` reads the
-- declared dimension out of the catalogue and refuses to write a vector of a
-- different length rather than letting Postgres round it off into an error
-- nobody can place.

create table chunks (
    id                uuid        primary key,
    clause_version_id uuid        not null references clause_versions (id) on delete cascade,

    section_key       text        not null,
    text              text        not null,

    -- Both clocks, copied from the version this chunk stands for.
    valid_from        date        not null,
    valid_to          date,
    recorded_at       timestamptz not null,
    recorded_until    timestamptz,

    embedding         vector(768) not null,
    embedding_model   text        not null,

    unique (clause_version_id, embedding_model)
);

-- The predicate the candidate fetch runs before anything is ranked.
create index chunks_asof on chunks (valid_from, valid_to, recorded_at, recorded_until);
create index chunks_section on chunks (section_key);
