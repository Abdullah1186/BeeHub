-- Review queue (spec §2.4): spaced repetition over things already got wrong.
--
-- Scheduling: FSRS-6, via the official `fsrs` package. The spec offers SM-2 or
-- FSRS and asks for the choice to be noted.
--
-- FSRS, because its advantage is largest exactly where BeeHub starts: SM-2
-- needs its parameters tuned per learner to behave well, while FSRS ships
-- defaults trained on ~700M reviews and beats SM-2 for ~99.5% of users with no
-- personalisation at all. It also models retrievability directly rather than
-- approximating spacing with a fixed multiplier, so "due" means "you are about
-- to forget this" rather than "some days have passed". Roughly 20-30% fewer
-- reviews for the same retention.
--
-- The scheduler's state lives in `fsrs_state` as JSONB rather than as columns.
-- FSRS-6 tracks stability, difficulty, state and step, and that shape belongs
-- to the library — pinning it into columns would make a library upgrade a
-- migration. Only `due_at` is promoted to a column, because it is the only
-- field queried.

create type review_item_kind as enum ('vocab', 'error_tag');

create table review_queue (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles(id) on delete cascade,

  kind        review_item_kind not null,
  -- The thing being reviewed. Exactly one is set, enforced below.
  vocab_id    uuid references vocab_items(id) on delete cascade,
  error_tag_id uuid references error_tags(id) on delete cascade,

  -- Denormalised so a due card renders without a join, and survives the
  -- source row being deleted mid-session.
  front       text not null,
  back        text not null,
  hint        text,

  due_at      timestamptz not null default now(),
  fsrs_state  jsonb not null,

  reps        int not null default 0,
  lapses      int not null default 0,
  -- Set when the item is retired: either learned well enough to stop, or
  -- dismissed by the learner. Retired rows are kept for the metrics.
  retired_at  timestamptz,
  retired_reason text,

  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  constraint exactly_one_source check (
    (kind = 'vocab'     and vocab_id is not null and error_tag_id is null) or
    (kind = 'error_tag' and error_tag_id is not null and vocab_id is null)
  )
);

-- The due query: everything not retired, ordered by when it came due.
create index review_due_idx on review_queue (user_id, retired_at, due_at);

-- One queue entry per source item. Adding a word twice should not double it.
create unique index review_vocab_unique on review_queue (user_id, vocab_id)
  where vocab_id is not null;
create unique index review_error_unique on review_queue (user_id, error_tag_id)
  where error_tag_id is not null;

create trigger review_queue_updated_at before update on review_queue
  for each row execute function set_updated_at();

alter table review_queue enable row level security;

create policy review_queue_all on review_queue
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());
