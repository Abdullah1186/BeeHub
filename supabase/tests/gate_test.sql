-- Position-gate and grounding tests (spec §5.2).
--
-- Run against a scratch database that has had the three migrations applied:
--   make db-test
--
-- These exist because the gate is the one property whose failure is invisible:
-- a leak produces a plausible-looking question about a page the learner has not
-- reached, and nothing errors. Two real bugs were caught here:
--
--   1. `array_length(source_chunk_ids, 1) >= 1` returns NULL for an empty array,
--      and a CHECK evaluating to NULL PASSES — so the grounding constraint was
--      silently inert. cardinality() is the correct form.
--   2. A multiplicative recency weight (`chunk_index * random()`) put 99.3% of
--      draws in the last ten pages and made earlier material unreachable.

\set ON_ERROR_STOP on

begin;

-- --- fixtures --------------------------------------------------------------

insert into auth.users (id, email) values
  ('11111111-1111-1111-1111-111111111111','learner@test'),
  ('22222222-2222-2222-2222-222222222222','other@test')
on conflict (id) do nothing;

insert into profiles (id, email) values
  ('11111111-1111-1111-1111-111111111111','learner@test'),
  ('22222222-2222-2222-2222-222222222222','other@test')
on conflict (id) do nothing;

-- A 200-page book; the learner is on page 40.
insert into resources (id, user_id, title, type, storage_path,
                       position_value, position_unit, total_length, ingest_status)
values ('aaaaaaaa-0000-0000-0000-000000000001',
        '11111111-1111-1111-1111-111111111111',
        'كتاب الاختبار','pdf','books/test.pdf',40,'page',200,'ok');

insert into resource_chunks (resource_id, chunk_index, text, text_normalized,
                             page_start, page_end, char_start, char_end)
select 'aaaaaaaa-0000-0000-0000-000000000001', g,
       'نص الصفحة '||g, 'نص الصفحه '||g, g, g, 0, 50
from generate_series(1,200) g;

-- An untracked resource: position_value IS NULL means "not tracked".
insert into resources (id, user_id, title, type, storage_path,
                       position_value, ingest_status)
values ('aaaaaaaa-0000-0000-0000-000000000002',
        '11111111-1111-1111-1111-111111111111',
        'ديوان شعر','pdf','books/poetry.pdf',null,'ok');

insert into resource_chunks (resource_id, chunk_index, text, text_normalized,
                             page_start, page_end, char_start, char_end)
select 'aaaaaaaa-0000-0000-0000-000000000002', g, 'بيت '||g, 'بيت '||g, g, g, 0, 20
from generate_series(1,30) g;

-- --- 1. resolve_max_page ---------------------------------------------------

do $$
begin
  assert resolve_max_page('aaaaaaaa-0000-0000-0000-000000000001',
                          '11111111-1111-1111-1111-111111111111') = 40,
         'owner with position=40 should resolve to 40';
  assert resolve_max_page('aaaaaaaa-0000-0000-0000-000000000002',
                          '11111111-1111-1111-1111-111111111111') = 2147483647,
         'untracked resource should be unrestricted';
  assert resolve_max_page('aaaaaaaa-0000-0000-0000-000000000001',
                          '22222222-2222-2222-2222-222222222222') = -1,
         'non-owner must get -1';
  assert resolve_max_page('aaaaaaaa-0000-0000-0000-000000000099',
                          '11111111-1111-1111-1111-111111111111') = -1,
         'missing resource must get -1';
  raise notice 'PASS resolve_max_page';
end $$;

-- --- 2. grounding constraint ----------------------------------------------

do $$
begin
  begin
    insert into generated_items (user_id, resource_id, item_type, payload,
                                 source_chunk_ids, max_page, difficulty_cefr)
    values ('11111111-1111-1111-1111-111111111111',
            'aaaaaaaa-0000-0000-0000-000000000001','short_answer',
            '{"q":"ungrounded"}'::jsonb, '{}', 5, 'A2');
    raise exception 'FAIL: an item with empty source_chunk_ids was accepted';
  exception when check_violation then
    null;
  end;

  begin
    insert into generated_items (user_id, resource_id, item_type, payload,
                                 source_chunk_ids, max_page, difficulty_cefr)
    values ('11111111-1111-1111-1111-111111111111',
            'aaaaaaaa-0000-0000-0000-000000000001','short_answer',
            '{"q":"null"}'::jsonb, null, 5, 'A2');
    raise exception 'FAIL: an item with NULL source_chunk_ids was accepted';
  exception when not_null_violation then
    null;
  end;
  raise notice 'PASS grounding constraint rejects ungrounded items';
end $$;

-- --- 3. window gating ------------------------------------------------------

do $$
declare v_pmax int; v_max int := 0; v_leak int;
begin
  for i in 1..1000 loop
    select coalesce(max(page_end),0)::int into v_pmax
    from select_chunk_window('aaaaaaaa-0000-0000-0000-000000000001',
                             '11111111-1111-1111-1111-111111111111', 3, true);
    if v_pmax > v_max then v_max := v_pmax; end if;
  end loop;
  assert v_max <= 40, format('GATE BREACH: returned page %s, limit 40', v_max);

  select count(*) into v_leak
  from select_chunk_window('aaaaaaaa-0000-0000-0000-000000000001',
                           '22222222-2222-2222-2222-222222222222', 3, true);
  assert v_leak = 0, 'cross-user access leaked rows';
  raise notice 'PASS window gate (1000 draws, max page %)', v_max;
end $$;

-- --- 4. position rollback --------------------------------------------------

do $$
declare v_pmax int; v_max int := 0;
begin
  update resources set position_value = 10
   where id = 'aaaaaaaa-0000-0000-0000-000000000001';
  for i in 1..300 loop
    select coalesce(max(page_end),0)::int into v_pmax
    from select_chunk_window('aaaaaaaa-0000-0000-0000-000000000001',
                             '11111111-1111-1111-1111-111111111111', 3, true);
    if v_pmax > v_max then v_max := v_pmax; end if;
  end loop;
  assert v_max <= 10, format('rollback breach: page %s after moving back to 10', v_max);
  update resources set position_value = 40
   where id = 'aaaaaaaa-0000-0000-0000-000000000001';
  raise notice 'PASS position rollback respected';
end $$;

-- --- 5. contiguity ---------------------------------------------------------

do $$
declare v_idx int[]; bad int := 0;
begin
  for i in 1..200 loop
    select array_agg(chunk_index order by chunk_index) into v_idx
    from select_chunk_window('aaaaaaaa-0000-0000-0000-000000000001',
                             '11111111-1111-1111-1111-111111111111', 3, true);
    if v_idx is not null and array_length(v_idx,1) > 1 then
      for j in 2..array_length(v_idx,1) loop
        if v_idx[j] <> v_idx[j-1] + 1 then bad := bad + 1; end if;
      end loop;
    end if;
  end loop;
  assert bad = 0, 'windows must be contiguous for a coherent passage';
  raise notice 'PASS window contiguity';
end $$;

-- --- 6. recency mixture ----------------------------------------------------
-- Recent material should be favoured, but older material must stay reachable.

do $$
declare v_min int; early int := 0; late int := 0;
begin
  for i in 1..2000 loop
    select min(page_start)::int into v_min
    from select_chunk_window('aaaaaaaa-0000-0000-0000-000000000001',
                             '11111111-1111-1111-1111-111111111111', 3, true);
    if v_min is null then continue; end if;
    if v_min <= 20 then early := early + 1; else late := late + 1; end if;
  end loop;
  assert early > 0, 'early material became unreachable — recency bias too strong';
  assert late > early, 'recent material should still be favoured';
  raise notice 'PASS recency mixture (early=%, late=%)', early, late;
end $$;

-- --- 7. serve-time gate ----------------------------------------------------
-- An item generated earlier must stop being served if it is now out of range.

do $$
declare v_served text;
begin
  insert into generated_items (user_id, resource_id, item_type, payload,
                               source_chunk_ids, max_page, difficulty_cefr)
  select '11111111-1111-1111-1111-111111111111',
         'aaaaaaaa-0000-0000-0000-000000000001','short_answer',
         '{"q":"in range"}'::jsonb, array[c.id], 35, 'A2'
  from resource_chunks c
  where c.resource_id = 'aaaaaaaa-0000-0000-0000-000000000001' and c.page_end = 35;

  insert into generated_items (user_id, resource_id, item_type, payload,
                               source_chunk_ids, max_page, difficulty_cefr)
  select '11111111-1111-1111-1111-111111111111',
         'aaaaaaaa-0000-0000-0000-000000000001','short_answer',
         '{"q":"spoiler"}'::jsonb, array[c.id], 150, 'A2'
  from resource_chunks c
  where c.resource_id = 'aaaaaaaa-0000-0000-0000-000000000001' and c.page_end = 150;

  select payload->>'q' into v_served
  from next_practice_item('11111111-1111-1111-1111-111111111111', null);

  assert v_served = 'in range',
         format('serve-time gate failed: served %s', coalesce(v_served,'<null>'));
  raise notice 'PASS serve-time gate withholds out-of-range items';
end $$;

-- --- 8. deleting a resource -----------------------------------------------
-- Chunks, generated items and jobs go with the resource; attempts and
-- vocabulary survive with resource_id set to null, because they are the
-- learner's record of work done rather than part of the book.

do $$
declare v_chunks int; v_items int; v_attempts int;
begin
  insert into attempts (user_id, resource_id, mode, item_type, prompt_text,
                        user_answer, difficulty_cefr)
  values ('11111111-1111-1111-1111-111111111111',
          'aaaaaaaa-0000-0000-0000-000000000001',
          'questions', 'short_answer', 'q', 'a', 'A2');

  delete from resources where id = 'aaaaaaaa-0000-0000-0000-000000000001';

  select count(*) into v_chunks from resource_chunks
   where resource_id = 'aaaaaaaa-0000-0000-0000-000000000001';
  select count(*) into v_items from generated_items
   where resource_id = 'aaaaaaaa-0000-0000-0000-000000000001';
  select count(*) into v_attempts from attempts
   where user_id = '11111111-1111-1111-1111-111111111111';

  assert v_chunks = 0, format('chunks should cascade, %s remain', v_chunks);
  assert v_items = 0, format('generated items should cascade, %s remain', v_items);
  assert v_attempts > 0, 'attempts must SURVIVE a resource delete';
  raise notice 'PASS delete cascades chunks but keeps history';
end $$;

rollback;
