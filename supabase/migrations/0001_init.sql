-- BeeHub initial schema.
--
-- Shape follows spec §4, with three deliberate departures documented inline:
--   1. embedding is vector(1024), not vector(1536) — Voyage voyage-4-lite, and
--      safely under pgvector's 2000-dim HNSW ceiling.
--   2. chunks carry page_start/page_end (not a single page_or_timestamp) and
--      both are NOT NULL, because the §5.2 position gate depends on them.
--   3. resources carry ingest_status/ingest_report so a badly-extracted PDF is
--      quarantined rather than silently turned into practice.

create extension if not exists vector;
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------

-- Supabase Auth owns auth.users. Never create a parallel users table; mirror it.
create table profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  email         text not null,
  target_level  text check (target_level in ('A1','A2','B1','B2','C1','C2')),
  daily_goal    int  not null default 10,
  dialect_pref  text not null default 'MSA',
  created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- resources
-- ---------------------------------------------------------------------------

create type resource_type as enum ('pdf','book','poetry','video','podcast');
create type position_unit as enum ('page','minute','percent');

create table resources (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles(id) on delete cascade,
  title          text not null,
  author         text,
  type           resource_type not null,
  storage_path   text,
  url            text,
  level_hint     text check (level_hint in ('A1','A2','B1','B2','C1','C2')),
  tags           text[] not null default '{}',

  -- How far the learner has actually got. The gate in §5.2 reads this.
  -- NULL means "not tracked" (e.g. a poetry collection read out of order),
  -- which the selector treats as "the whole resource is fair game".
  position_value int,
  position_unit  position_unit,
  total_length   int,

  ingest_status  text not null default 'pending'
                 check (ingest_status in ('pending','extracting','ok','degraded','failed')),
  ingest_report  jsonb not null default '{}'::jsonb,

  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),

  constraint pdf_needs_storage check (type <> 'pdf' or storage_path is not null),
  constraint position_non_negative check (position_value is null or position_value >= 0)
);
create index resources_user_idx on resources (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- chunks
-- ---------------------------------------------------------------------------

create table resource_chunks (
  id              uuid primary key default gen_random_uuid(),
  resource_id     uuid not null references resources(id) on delete cascade,
  chunk_index     int  not null,

  text            text not null,  -- diacritics preserved: display + embedding (§7)
  text_normalized text not null,  -- folded: keyword search only, never displayed

  -- Equal in Phase 1: the chunker never crosses a page, because a chunk
  -- spanning pages 40-41 is un-gateable when the learner is on page 40.
  -- Both columns exist so Phase 2 can relax that without a migration.
  page_start      int not null,
  page_end        int not null,
  char_start      int not null,
  char_end        int not null,
  token_estimate  int,

  embedding       vector(1024),
  embedding_model text,

  created_at      timestamptz not null default now(),

  unique (resource_id, chunk_index),
  constraint page_order check (page_end >= page_start),
  constraint char_order check (char_end > char_start)
);

-- The position gate rides this index; it is not optional.
create index chunks_gate_idx on resource_chunks (resource_id, page_end, chunk_index);
create index chunks_fts_idx  on resource_chunks using gin (text_normalized gin_trgm_ops);

-- Build HNSW only after the first bulk load; on an empty table the index is
-- built again from scratch as rows arrive.
create index chunks_vec_idx on resource_chunks
  using hnsw (embedding vector_cosine_ops) with (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------------
-- cost telemetry (spec §7: "every model call is logged")
-- ---------------------------------------------------------------------------

create table model_calls (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references profiles(id) on delete set null,

  -- The provenance chain that lets an eval say "this regression came from
  -- prompt_hash abc123". skill_version is the declared version; prompt_hash is
  -- sha256 of the FULLY RENDERED prompt, so a shared-include edit changes it.
  skill_id      text not null,
  skill_version int  not null,
  prompt_hash   text not null,

  model         text not null,
  pool          text not null,

  input_tokens                int not null default 0,
  output_tokens               int not null default 0,
  cache_creation_input_tokens int not null default 0,
  cache_read_input_tokens     int not null default 0,
  cost_usd      numeric(10,6) not null default 0,
  latency_ms    int,
  batch_id      text,

  status        text not null
                check (status in ('ok','validation_failed','api_error','refused')),
  error_detail  text,
  created_at    timestamptz not null default now()
);
create index model_calls_time_idx  on model_calls (created_at desc);
create index model_calls_skill_idx on model_calls (skill_id, prompt_hash);

-- ---------------------------------------------------------------------------
-- generated practice (cached, per §4: never regenerate an unseen question)
-- ---------------------------------------------------------------------------

create table generated_items (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  resource_id     uuid not null references resources(id) on delete cascade,
  item_type       text not null,

  -- question + key_points[{id,text,source_quote}] + difficulty rationale.
  -- key_points are produced at GENERATION time so grading only has to decide
  -- whether each was conveyed — a far more repeatable judgement.
  payload         jsonb not null,

  source_chunk_ids uuid[] not null,
  -- Denormalised max(page_end) of the sources, so the gate is a single
  -- integer comparison rather than a join on every serve.
  max_page        int not null,

  difficulty_cefr text not null
                  check (difficulty_cefr in ('A1','A2','B1','B2','C1','C2')),
  model_call_id   uuid references model_calls(id) on delete set null,
  human_flagged   bool not null default false,
  consumed_at     timestamptz,
  created_at      timestamptz not null default now(),

  -- §5.2 enforced in the database, not only in application code.
  --
  -- NOTE: array_length('{}', 1) returns NULL, not 0, and a CHECK that evaluates
  -- to NULL PASSES. Writing this as `array_length(...) >= 1` makes the
  -- constraint silently inert and lets an ungrounded item reach the learner.
  -- cardinality() returns 0 for an empty array, so it is the safe form.
  constraint must_be_grounded check (cardinality(source_chunk_ids) >= 1)
);
create index generated_items_serve_idx
  on generated_items (user_id, resource_id, consumed_at, max_page);

-- ---------------------------------------------------------------------------
-- attempts, errors, vocab, levels
-- ---------------------------------------------------------------------------

create table attempts (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references profiles(id) on delete cascade,
  resource_id       uuid references resources(id) on delete set null,
  generated_item_id uuid references generated_items(id) on delete set null,

  mode              text not null,
  item_type         text not null,
  prompt_text       text not null,
  user_answer       text not null,
  input_method      text not null default 'typed'
                    check (input_method in ('typed','photo','speech')),
  raw_transcript    text,

  -- Scored separately so reading and writing CEFR can diverge (§2.5).
  -- content_score: did they answer, judged against the cited source.
  -- language_score: grammar/orthography. A right answer in broken Arabic
  -- scores high content, low language — which is the honest signal.
  content_score     numeric(4,3),
  language_score    numeric(4,3),
  score             numeric(4,3),  -- combined, computed in Python not by the model
  max_score         numeric(4,3) not null default 1.0,

  difficulty_cefr   text not null
                    check (difficulty_cefr in ('A1','A2','B1','B2','C1','C2')),
  grade_payload     jsonb,
  gradable          bool not null default true,
  -- Set when the model's own holistic score disagrees sharply with the computed
  -- one; these become free eval cases.
  review_flagged    bool not null default false,
  model_call_id     uuid references model_calls(id) on delete set null,
  created_at        timestamptz not null default now()
);
create index attempts_user_idx  on attempts (user_id, created_at desc);
create index attempts_skill_idx on attempts (user_id, difficulty_cefr, created_at desc);

create table error_tags (
  id           uuid primary key default gen_random_uuid(),
  attempt_id   uuid not null references attempts(id) on delete cascade,
  user_id      uuid not null references profiles(id) on delete cascade,

  -- Constrained to the controlled vocabulary in skills/_shared/error-taxonomy.yaml.
  -- Free-text categories make the metrics tab useless (§5.6), so the closed
  -- Pydantic enum is the real guard; this column stores its value.
  category     text not null,
  subcategory  text not null,
  span         text not null,
  correction   text,
  explanation  text not null,
  severity     text not null check (severity in ('minor','moderate','blocking')),
  created_at   timestamptz not null default now()
);
create index error_tags_user_idx on error_tags (user_id, category, created_at desc);

create table vocab_items (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references profiles(id) on delete cascade,
  resource_id       uuid references resources(id) on delete set null,
  source_chunk_id   uuid references resource_chunks(id) on delete set null,

  arabic            text not null,  -- as it appears, diacritics intact
  arabic_normalized text not null,  -- folded, for dedupe and matching
  root              text,
  pos               text,
  translation       text not null,
  context_sentence  text,
  first_seen_at     timestamptz not null default now(),

  unique (user_id, arabic_normalized)
);
create index vocab_user_idx on vocab_items (user_id, first_seen_at desc);

create table level_estimates (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  skill           text not null check (skill in ('reading','writing','speaking','vocab')),

  cefr_level      text not null check (cefr_level in ('A1','A2','B1','B2','C1','C2')),
  -- The Elo/theta value CEFR is DERIVED from. Stored as the source of truth so
  -- the update rule can change (decaying K, Glicko) without rewriting history.
  numeric_ability numeric(6,3) not null,
  confidence      numeric(4,3) not null,
  n_observations  int not null,
  computed_at     timestamptz not null default now()
);
create index level_estimates_idx on level_estimates (user_id, skill, computed_at desc);

-- ---------------------------------------------------------------------------
-- ingestion job queue (Railway worker polls this; no Edge Functions, so the
-- worker runs the same Python and the same PyMuPDF as the tests)
-- ---------------------------------------------------------------------------

create table ingest_jobs (
  id           uuid primary key default gen_random_uuid(),
  resource_id  uuid not null references resources(id) on delete cascade,
  status       text not null default 'queued'
               check (status in ('queued','running','done','error')),
  attempts     int  not null default 0,
  last_error   text,
  locked_at    timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index ingest_jobs_queue_idx on ingest_jobs (status, created_at);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger resources_updated_at   before update on resources
  for each row execute function set_updated_at();
create trigger ingest_jobs_updated_at before update on ingest_jobs
  for each row execute function set_updated_at();

-- New auth user -> profile row.
create or replace function handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();
