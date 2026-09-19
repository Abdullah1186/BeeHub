-- LOCAL TESTING ONLY — never applied to the real project.
--
-- Supabase provides the `auth` schema, `auth.users`, and `auth.uid()`. This
-- stand-in recreates just enough of them that the migrations in
-- supabase/migrations/ can be applied and exercised against a plain Postgres
-- container offline.
--
-- It deliberately lives outside supabase/migrations/ so it can never be picked
-- up by `supabase db push`.

create schema if not exists auth;

create table if not exists auth.users (
  id    uuid primary key default gen_random_uuid(),
  email text
);

-- Supabase derives this from the request JWT. Locally, set it per session:
--   set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
create or replace function auth.uid() returns uuid
language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;

do $$
begin
  create role authenticated;
exception when duplicate_object then
  null;
end $$;
