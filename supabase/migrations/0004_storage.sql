-- Storage bucket and its access policies.
--
-- This was missing: the earlier migrations created every table but never the
-- bucket, so uploads failed with "Bucket not found" at the first real attempt.
--
-- The bucket is PRIVATE. Uploaded books are the learner's own material and must
-- not be readable by guessing a URL.
--
-- Object paths are `<user_id>/<resource_id>.pdf`, so the first path segment is
-- the owner. Every policy below checks it against auth.uid(), which mirrors the
-- RLS on `resources` in 0002_rls.sql.

-- Self-skipping. The `storage` schema is provided by Supabase and does not
-- exist in a plain Postgres container, so the local harness and CI would
-- otherwise fail here. Guarding inside the migration keeps that knowledge in
-- one place rather than duplicated in the Makefile and the CI workflow --
-- where it was, until CI forgot it.
do $$
begin
  if to_regclass('storage.buckets') is null then
    raise notice 'storage schema not present (plain Postgres) - skipping bucket setup';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('resources', 'resources', false, 52428800, array['application/pdf'])
  on conflict (id) do update
    set public             = excluded.public,
        file_size_limit    = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

  -- Policies are dropped first so this migration can be re-applied safely.
  drop policy if exists "own files: read"   on storage.objects;
  drop policy if exists "own files: upload" on storage.objects;
  drop policy if exists "own files: update" on storage.objects;
  drop policy if exists "own files: delete" on storage.objects;

  execute $p$
    create policy "own files: read" on storage.objects
      for select to authenticated
      using (bucket_id = 'resources'
             and (storage.foldername(name))[1] = auth.uid()::text)
  $p$;
  execute $p$
    create policy "own files: upload" on storage.objects
      for insert to authenticated
      with check (bucket_id = 'resources'
                  and (storage.foldername(name))[1] = auth.uid()::text)
  $p$;
  execute $p$
    create policy "own files: update" on storage.objects
      for update to authenticated
      using (bucket_id = 'resources'
             and (storage.foldername(name))[1] = auth.uid()::text)
  $p$;
  execute $p$
    create policy "own files: delete" on storage.objects
      for delete to authenticated
      using (bucket_id = 'resources'
             and (storage.foldername(name))[1] = auth.uid()::text)
  $p$;
end $$;

-- The ingestion worker downloads with the service role, which bypasses all of
-- the above by design — it fetches files for a user whose JWT it does not hold.
