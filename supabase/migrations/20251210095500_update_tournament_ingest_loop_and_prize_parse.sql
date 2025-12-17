-- Organizer list table to drive pg_cron ingest.
create table if not exists public.tournament_ingest_organizers (
  username text primary key,
  active boolean default true,
  note text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.tournament_ingest_organizers enable row level security;

drop policy if exists tournament_ingest_organizers_select_public on public.tournament_ingest_organizers;
create policy tournament_ingest_organizers_select_public
  on public.tournament_ingest_organizers
  for select
  using (true);

drop policy if exists tournament_ingest_organizers_write_service_role on public.tournament_ingest_organizers;
create policy tournament_ingest_organizers_write_service_role
  on public.tournament_ingest_organizers
  for all
  to authenticated, service_role
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Seed initial organizers (idempotent).
insert into public.tournament_ingest_organizers (username, active)
values
  ('investygator', true),
  ('royaleagle', true),
  ('bunsbagsandcaps', true),
  ('dejota', true),
  ('silentriot', true),
  ('ehmaywuntee', true),
  ('lorkus', true),
  ('clove71', true),
  ('yggspl-official', true),
  ('blazekos', true),
  ('bulldog1205', true),
  ('fluidflame', true),
  ('keeegs', true),
  ('pipipetra', true)
on conflict (username) do update
set active = excluded.active,
    updated_at = now();


-- Helper to normalize a prize item to JSON.
create or replace function public.normalize_prize_item(item jsonb)
returns jsonb
language plpgsql
as $$
declare
  amount numeric;
  token text;
  text_label text;
  usd_value numeric;
begin
  if item is null then
    return null;
  end if;

  amount := nullif(item->>'amount', '')::numeric;
  if amount is null then
    amount := nullif(item->>'qty', '')::numeric;
  end if;
  if amount is null then
    amount := nullif(item->>'value', '')::numeric;
  end if;

  token := item->>'token';
  if token is null or token = '' then
    token := item->>'type';
  end if;

  text_label := item->>'text';
  usd_value := nullif(item->>'usd_value', '')::numeric;

  if token is null and text_label is null then
    return null;
  end if;

  return jsonb_build_object(
    'amount', amount,
    'token', token,
    'text', text_label,
    'usd_value', usd_value
  );
end;
$$ stable;


-- Improved ingest: loop over organizer table, richer prize parsing, optional date cutoff.
create or replace function public.refresh_tournament_ingest(
  organizer text default null,
  max_age_days integer default 400
)
returns void
language plpgsql
as $$
declare
  org_list text[];
  org text;
  cutoff_ts timestamptz := now() - (max_age_days || ' days')::interval;
  list_resp jsonb;
  item_rec record;
  detail_resp jsonb;
  players jsonb;
  player_rec record;
  payout_rec record;
  payout_item_rec record;
  direct_item_rec record;
  tid text;
  start_date timestamptz;
  status text;
  entrants integer;
  payouts jsonb;
  allowed_cards jsonb;
  prize_tokens jsonb;
  prize_text_parts text[];
  direct_prize jsonb;
  finish_int integer;
  norm_item jsonb;
  now_ts timestamptz := now();
begin
  if organizer is not null then
    org_list := array[organizer];
  else
    select array_agg(username order by username)
    into org_list
    from public.tournament_ingest_organizers
    where active is true;
  end if;

  if org_list is null or array_length(org_list, 1) is null then
    raise notice 'No organizers configured for ingest.';
    return;
  end if;

  foreach org in array org_list
  loop
    select content::jsonb
      into list_resp
    from net.http_get(url => format('https://api.splinterlands.com/tournaments/mine?username=%s', org))
    limit 1;

    if list_resp is null or jsonb_typeof(list_resp) <> 'array' then
      raise notice 'No tournaments returned for %', org;
      continue;
    end if;

    for item_rec in select value from jsonb_array_elements(list_resp) as t(value)
    loop
      tid := item_rec.value->>'id';
      if tid is null or tid = '' then
        continue;
      end if;

      select content::jsonb
        into detail_resp
      from net.http_get(
        url => format('https://api.splinterlands.com/tournaments/find?id=%s&username=%s', tid, org)
      )
      limit 1;

      start_date := coalesce(
        (detail_resp->>'start_date')::timestamptz,
        (item_rec.value->>'start_date')::timestamptz
      );
      if start_date is not null and start_date < cutoff_ts then
        continue;
      end if;

      status := coalesce(
        detail_resp->>'status',
        detail_resp->>'current_round',
        item_rec.value->>'status'
      );
      entrants := coalesce(
        (detail_resp->>'players_registered')::integer,
        (detail_resp->>'num_players')::integer,
        (item_rec.value->>'players_registered')::integer
      );
      payouts := coalesce(
        detail_resp#>'{data,prizes,payouts}',
        detail_resp#>'{prizes,payouts}',
        item_rec.value#>'{data,prizes,payouts}'
      );
      allowed_cards := coalesce(
        detail_resp#>'{data,allowed_cards}',
        item_rec.value#>'{data,allowed_cards}'
      );

      insert into public.tournament_events (
        tournament_id,
        organizer,
        name,
        start_date,
        status,
        entrants,
        entry_fee_token,
        entry_fee_amount,
        payouts,
        allowed_cards,
        raw_list,
        raw_detail,
        updated_at
      )
      values (
        tid,
        org,
        coalesce(item_rec.value->>'name', detail_resp->>'name', tid),
        start_date,
        status,
        entrants,
        null,
        null,
        payouts,
        allowed_cards,
        item_rec.value,
        detail_resp,
        now_ts
      )
      on conflict (tournament_id) do update
      set
        organizer = excluded.organizer,
        name = excluded.name,
        start_date = excluded.start_date,
        status = excluded.status,
        entrants = excluded.entrants,
        payouts = excluded.payouts,
        allowed_cards = excluded.allowed_cards,
        raw_list = excluded.raw_list,
        raw_detail = excluded.raw_detail,
        updated_at = excluded.updated_at;

      players := coalesce(detail_resp->'players', '[]'::jsonb);
      if jsonb_typeof(players) <> 'array' then
        continue;
      end if;

      for player_rec in select value from jsonb_array_elements(players) as t(value)
      loop
        finish_int := coalesce((player_rec.value->>'finish')::integer, 0);
        prize_tokens := '[]'::jsonb;
        prize_text_parts := '{}';
        direct_prize := coalesce(
          player_rec.value->'ext_prize_info',
          player_rec.value->'prizes',
          player_rec.value->'prize',
          player_rec.value->'player_prize'
        );

        -- Parse direct prize payload.
        if jsonb_typeof(direct_prize) = 'array' then
          for direct_item_rec in select value from jsonb_array_elements(direct_prize) as t(value)
          loop
            norm_item := normalize_prize_item(direct_item_rec.value);
            if norm_item is not null then
              prize_tokens := prize_tokens || jsonb_build_array(norm_item);
              prize_text_parts := array_append(
                prize_text_parts,
                coalesce(
                  trim(both ' ' from format('%s %s', norm_item->>'amount', norm_item->>'token')),
                  norm_item->>'text'
                )
              );
            end if;
          end loop;
        elsif jsonb_typeof(direct_prize) = 'object' then
          norm_item := normalize_prize_item(direct_prize);
          if norm_item is not null then
            prize_tokens := prize_tokens || jsonb_build_array(norm_item);
            prize_text_parts := array_append(
              prize_text_parts,
              coalesce(
                trim(both ' ' from format('%s %s', norm_item->>'amount', norm_item->>'token')),
                norm_item->>'text'
              )
            );
          end if;
        elsif jsonb_typeof(direct_prize) = 'string' then
          prize_text_parts := array_append(prize_text_parts, direct_prize::text);
        end if;

        -- Infer prizes from payout ranges.
        if jsonb_typeof(payouts) = 'array' then
          for payout_rec in select value from jsonb_array_elements(payouts) as t(value)
          loop
            if not ((payout_rec.value->>'start_place')::int <= finish_int
                 and finish_int <= (payout_rec.value->>'end_place')::int) then
              continue;
            end if;
            for payout_item_rec in select value from jsonb_array_elements(coalesce(payout_rec.value->'items', '[]'::jsonb)) as t(value)
            loop
              norm_item := normalize_prize_item(payout_item_rec.value);
              if norm_item is not null then
                prize_tokens := prize_tokens || jsonb_build_array(norm_item);
                prize_text_parts := array_append(
                  prize_text_parts,
                  coalesce(
                    trim(both ' ' from format('%s %s', norm_item->>'amount', norm_item->>'token')),
                    norm_item->>'text'
                  )
                );
              end if;
            end loop;
          end loop;
        end if;

        -- Deduplicate prize text and null out empty tokens.
        prize_text_parts := (
          select array_agg(distinct t) from unnest(prize_text_parts) as t where t is not null and t <> ''
        );
        if prize_tokens is not null and jsonb_array_length(prize_tokens) = 0 then
          prize_tokens := null;
        end if;

        insert into public.tournament_results (
          tournament_id,
          player,
          finish,
          prize_tokens,
          prize_text,
          raw,
          updated_at
        )
        values (
          tid,
          coalesce(player_rec.value->>'player', player_rec.value->>'username'),
          nullif(player_rec.value->>'finish', '')::integer,
          prize_tokens,
          case when prize_text_parts is null then null else array_to_string(prize_text_parts, '; ') end,
          player_rec.value,
          now_ts
        )
        on conflict (tournament_id, player) do update
        set
          finish = excluded.finish,
          prize_tokens = excluded.prize_tokens,
          prize_text = excluded.prize_text,
          raw = excluded.raw,
          updated_at = excluded.updated_at;
      end loop;
    end loop;
  end loop;
end;
$$;


-- Replace the cron job to use organizer table and new parsing.
select cron.unschedule('tournament-ingest-daily');
select
  cron.schedule(
    'tournament-ingest-daily',
    '15 7 * * *',
    $$select public.refresh_tournament_ingest();$$
  );
