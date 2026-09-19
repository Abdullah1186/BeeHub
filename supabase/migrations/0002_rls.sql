-- Row Level Security.
--
-- Enabled from day one even though BeeHub is single-user today. Retrofitting RLS
-- after the app has assumed an unfiltered service-role client means rewriting
-- every query, and it demotes the §5.2 position gate from a database guarantee
-- to an application promise.
--
-- The service role bypasses all of this by design — that is why the ingestion
-- worker may use it and a request handler may never.

alter table profiles        enable row level security;
alter table resources       enable row level security;
alter table resource_chunks enable row level security;
alter table generated_items enable row level security;
alter table attempts        enable row level security;
alter table error_tags      enable row level security;
alter table vocab_items     enable row level security;
alter table level_estimates enable row level security;
alter table model_calls     enable row level security;
alter table ingest_jobs     enable row level security;

-- --- profiles --------------------------------------------------------------

create policy profiles_select on profiles
  for select using (id = auth.uid());
create policy profiles_update on profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- --- directly owned tables -------------------------------------------------

create policy resources_all on resources
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy generated_items_all on generated_items
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy attempts_all on attempts
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy error_tags_all on error_tags
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy vocab_items_all on vocab_items
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy level_estimates_all on level_estimates
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Telemetry is readable by its owner; only the backend writes it.
create policy model_calls_select on model_calls
  for select using (user_id = auth.uid());

-- --- chunks: no user_id column, so join through the parent resource ---------

create policy resource_chunks_select on resource_chunks
  for select using (
    exists (
      select 1 from resources r
      where r.id = resource_chunks.resource_id
        and r.user_id = auth.uid()
    )
  );

-- Chunks are written only by the ingestion worker (service role), which
-- bypasses RLS. No insert/update/delete policy is granted to end users.

-- --- jobs: owner may watch progress; only the worker mutates ---------------

create policy ingest_jobs_select on ingest_jobs
  for select using (
    exists (
      select 1 from resources r
      where r.id = ingest_jobs.resource_id
        and r.user_id = auth.uid()
    )
  );
