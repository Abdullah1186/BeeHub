-- Retrieval functions.
--
-- The §5.2 position gate lives here and nowhere else. Every retrieval path goes
-- through one of these functions, so "never generate from material the learner
-- has not reached" is enforced in one auditable place rather than repeated (and
-- eventually forgotten) at each call site.
--
-- Gate semantics, identical in every function below:
--   position_value IS NULL -> not tracked, the whole resource is available
--   position_value = N     -> only chunks with page_end <= N
--
-- security definer + a pinned search_path so the gate cannot be bypassed by a
-- caller's schema, and ownership is re-checked explicitly against p_user_id.

-- ---------------------------------------------------------------------------
-- resolve_max_page: the gate itself, factored out so it cannot drift.
-- ---------------------------------------------------------------------------
create or replace function resolve_max_page(p_resource_id uuid, p_user_id uuid)
returns int
language plpgsql stable security definer set search_path = public as $$
declare
  v_position int;
  v_owner    uuid;
begin
  select user_id, position_value into v_owner, v_position
  from resources where id = p_resource_id;

  if v_owner is null or v_owner <> p_user_id then
    -- Not yours (or not there): expose nothing, and do not leak which it was.
    return -1;
  end if;

  -- NULL position means untracked, so everything the resource has is fair game.
  return coalesce(v_position, 2147483647);
end;
$$;

-- ---------------------------------------------------------------------------
-- select_chunk_window
--
-- Question generation needs a COHERENT PASSAGE, not a top-k scatter. Vector
-- similarity returns semantically related but narratively disconnected
-- fragments — exactly the input that produces incoherent comprehension
-- questions. So generation samples a contiguous run of chunks, biased toward
-- what the learner most recently read.
-- ---------------------------------------------------------------------------
create or replace function select_chunk_window(
  p_resource_id uuid,
  p_user_id     uuid,
  p_window      int default 3,
  p_recency_bias boolean default true
)
returns table (
  id          uuid,
  chunk_index int,
  text        text,
  page_start  int,
  page_end    int
)
language plpgsql stable security definer set search_path = public as $$
declare
  v_max_page   int;
  v_start_index int;
begin
  v_max_page := resolve_max_page(p_resource_id, p_user_id);
  if v_max_page < 0 then
    return;
  end if;

  -- Pick the first chunk of the window from what is visible.
  --
  -- Recency bias is a MIXTURE, not a weighting: 60% of the time draw uniformly
  -- from the most recent third of what the learner has read, otherwise draw
  -- uniformly from everything. A multiplicative weight like
  -- `chunk_index * random()` concentrates ~99% of draws in the last few pages
  -- and makes earlier material effectively unreachable, which silently removes
  -- review of anything but the newest pages.
  if p_recency_bias and random() < 0.6 then
    select c.chunk_index into v_start_index
    from resource_chunks c
    where c.resource_id = p_resource_id
      and c.page_end   <= v_max_page
      and c.chunk_index >= (
        select coalesce(max(c2.chunk_index), 0) * 2 / 3
        from resource_chunks c2
        where c2.resource_id = p_resource_id
          and c2.page_end   <= v_max_page
      )
    order by random()
    limit 1;
  end if;

  if v_start_index is null then
    select c.chunk_index into v_start_index
    from resource_chunks c
    where c.resource_id = p_resource_id
      and c.page_end   <= v_max_page
    order by random()
    limit 1;
  end if;

  if v_start_index is null then
    return;
  end if;

  -- Return the contiguous run starting there, still gated: the window must not
  -- run past the learner's position even when it starts before it.
  return query
  select c.id, c.chunk_index, c.text, c.page_start, c.page_end
  from resource_chunks c
  where c.resource_id = p_resource_id
    and c.page_end    <= v_max_page
    and c.chunk_index >= v_start_index
    and c.chunk_index <  v_start_index + p_window
  order by c.chunk_index;
end;
$$;

-- ---------------------------------------------------------------------------
-- match_chunks
--
-- Semantic search, gated. Used for vocab context and Phase 2 thematic practice
-- — NOT for question generation (see select_chunk_window above).
-- ---------------------------------------------------------------------------
create or replace function match_chunks(
  p_resource_id     uuid,
  p_user_id         uuid,
  p_query_embedding vector(1024),
  p_limit           int default 5
)
returns table (
  id          uuid,
  chunk_index int,
  text        text,
  page_start  int,
  page_end    int,
  similarity  float
)
language plpgsql stable security definer set search_path = public as $$
declare
  v_max_page int;
begin
  v_max_page := resolve_max_page(p_resource_id, p_user_id);
  if v_max_page < 0 then
    return;
  end if;

  return query
  select c.id, c.chunk_index, c.text, c.page_start, c.page_end,
         1 - (c.embedding <=> p_query_embedding) as similarity
  from resource_chunks c
  where c.resource_id = p_resource_id
    and c.page_end   <= v_max_page
    and c.embedding is not null
  order by c.embedding <=> p_query_embedding
  limit p_limit;
end;
$$;

-- ---------------------------------------------------------------------------
-- next_practice_item: serve a cached, grounded, in-range question.
-- Cheapest path — no model call when the bank has something unseen (§4).
-- ---------------------------------------------------------------------------
create or replace function next_practice_item(
  p_user_id     uuid,
  p_resource_id uuid default null
)
returns table (
  id              uuid,
  resource_id     uuid,
  item_type       text,
  payload         jsonb,
  difficulty_cefr text,
  max_page        int
)
language plpgsql stable security definer set search_path = public as $$
begin
  return query
  select g.id, g.resource_id, g.item_type, g.payload, g.difficulty_cefr, g.max_page
  from generated_items g
  join resources r on r.id = g.resource_id
  where g.user_id = p_user_id
    and g.consumed_at is null
    and g.human_flagged = false
    and (p_resource_id is null or g.resource_id = p_resource_id)
    -- Re-apply the gate at serve time: a learner can move their position
    -- BACKWARDS, and an item generated when they were further ahead must
    -- stop being served.
    and g.max_page <= coalesce(r.position_value, 2147483647)
    and r.ingest_status in ('ok','degraded')
  order by g.created_at
  limit 1;
end;
$$;

-- Callable by authenticated users; the functions re-check ownership themselves.
grant execute on function resolve_max_page(uuid, uuid)              to authenticated;
grant execute on function select_chunk_window(uuid, uuid, int, boolean) to authenticated;
grant execute on function match_chunks(uuid, uuid, vector, int)     to authenticated;
grant execute on function next_practice_item(uuid, uuid)            to authenticated;
