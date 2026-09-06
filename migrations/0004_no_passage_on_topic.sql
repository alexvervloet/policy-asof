-- A fourth outcome, from the distance floor added in phase 5.
--
-- "No rule was in force" and "the handbook says nothing about this" are
-- different refusals, and the second one did not exist when 0003 was written.
-- The check constraint is what caught the omission, on the first run of the
-- gate, which is the argument for having it spelled out rather than left to the
-- application to remember.

alter table answers drop constraint answers_outcome_check;

alter table answers add constraint answers_outcome_check
    check (outcome in ('answered', 'ambiguous-date', 'no-record',
                       'no-rule-in-force', 'no-passage-on-topic'));
