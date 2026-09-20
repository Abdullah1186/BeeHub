-- Let a user queue an ingestion job for their own resource.
--
-- 0002_rls.sql gave ingest_jobs a SELECT policy only, on the assumption that
-- the worker (service role) would be the only writer. But the UPLOAD path
-- queues the job, and that runs as the user — so the insert was rejected with
-- "new row violates row-level security policy for table ingest_jobs".
--
-- Insert is scoped the same way select is: the job's resource must belong to
-- the caller. Update and delete stay service-role-only, so a user cannot mark
-- their own job done or re-run it.

drop policy if exists ingest_jobs_insert on ingest_jobs;

create policy ingest_jobs_insert on ingest_jobs
  for insert to authenticated
  with check (
    exists (
      select 1 from resources r
      where r.id = ingest_jobs.resource_id
        and r.user_id = auth.uid()
    )
  );
