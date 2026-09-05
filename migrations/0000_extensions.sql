-- Extensions live in a migration, not in a preflight script. The container runs
-- migrations and nothing else, so anything the app needs at runtime has to come
-- into being here or the app dies on boot in the one environment that matters.

create extension if not exists vector;      -- retrieval, from phase 3
create extension if not exists btree_gist;  -- equality plus range overlap in one exclusion constraint
