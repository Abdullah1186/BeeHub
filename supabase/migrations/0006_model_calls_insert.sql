-- Let the API record its own telemetry.
--
-- 0002_rls.sql gave model_calls a SELECT policy only. Every insert was
-- therefore rejected by RLS — and because record_call() deliberately swallows
-- telemetry failures so a logging problem cannot break a user's request, the
-- rejection was silent. The table stayed empty and the Metrics tab reported
-- $0.0000 spend.
--
-- §7 is explicit: "Every model call is logged... You cannot optimise spend you
-- can't see." A silently empty telemetry table is the exact failure that rule
-- exists to prevent.
--
-- Insert is scoped to your own rows. Update and delete are granted to nobody,
-- so telemetry is append-only from the application's side.

drop policy if exists model_calls_insert on model_calls;

create policy model_calls_insert on model_calls
  for insert to authenticated
  with check (user_id = auth.uid());
