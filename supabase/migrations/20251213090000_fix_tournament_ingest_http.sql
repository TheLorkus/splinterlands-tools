-- Enable http extension for synchronous fetches (avoids pg_net request-id handling).
create extension if not exists http;

-- Remove the legacy overload to avoid cron ambiguity.
drop function if exists public.refresh_tournament_ingest(text);

-- Rewrite ingest to use http_get (synchronous) and keep the text,int signature.
create or replace function public.refresh_tournament_ingest(
  organizer text default null,
  max_age_days integer default 400
)
returns void
language plpgsql
set search_path to public, pg_temp
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
  event_status text;
  entrants integer;
  payouts jsonb;
  allowed_cards jsonb;
  prize_tokens jsonb;
  prize_text_parts text[];
  direct_prize jsonb;
  finish_int integer;
  norm_item jsonb;
  now_ts timestamptz := now();
  resp_code integer;
  resp_body text;
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
    select h.status, h.content
    into resp_code, resp_body
    from http_get(format('https://api.splinterlands.com/tournaments/mine?username=%s', org)) as h;

    if coalesce(resp_code, 0) >= 400 or resp_body is null then
      raise notice 'No tournaments returned for %', org;
      continue;
    end if;

    list_resp := nullif(resp_body, '')::jsonb;
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

      select h.status, h.content
      into resp_code, resp_body
      from http_get(format('https://api.splinterlands.com/tournaments/find?id=%s&username=%s', tid, org)) as h;

      if coalesce(resp_code, 0) >= 400 or resp_body is null then
        continue;
      end if;

      detail_resp := nullif(resp_body, '')::jsonb;
      if detail_resp is null then
        detail_resp := '{}'::jsonb;
      end if;

      start_date := coalesce(
        (detail_resp->>'start_date')::timestamptz,
        (item_rec.value->>'start_date')::timestamptz
      );
      if start_date is not null and start_date < cutoff_ts then
        continue;
      end if;

      event_status := coalesce(
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
        event_status,
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

-- Align cron job to the unambiguous signature/command.
do $$
declare
  job_exists boolean;
begin
  select exists(select 1 from cron.job where jobid = 6) into job_exists;
  if job_exists then
    perform cron.alter_job(6, command => 'select public.refresh_tournament_ingest(null::text, 400);');
  else
    perform cron.schedule(
      'tournament-ingest-daily',
      '15 7 * * *',
      'select public.refresh_tournament_ingest(null::text, 400);'
    );
  end if;
end
$$;
