-- Function: fetch daily tournament results for an organizer using pg_net.
-- Note: simplified prize parsing (stores raw player payload + any prize text).
create or replace function public.refresh_tournament_ingest(organizer text default 'lorkus')
returns void
language plpgsql
as $$
declare
  list_resp jsonb;
  item jsonb;
  detail_resp jsonb;
  players jsonb;
  player jsonb;
  tid text;
  name text;
  start_date timestamptz;
  status text;
  entrants integer;
  payouts jsonb;
  allowed_cards jsonb;
  prize_tokens jsonb;
  prize_text text;
  now_ts timestamptz := now();
begin
  select content::jsonb
    into list_resp
  from net.http_get(url => format('https://api.splinterlands.com/tournaments/mine?username=%s', organizer))
  limit 1;

  if list_resp is null or jsonb_typeof(list_resp) <> 'array' then
    raise notice 'No tournaments returned for %', organizer;
    return;
  end if;

  for item in select * from jsonb_array_elements(list_resp)
  loop
    tid := item->>'id';
    if tid is null or tid = '' then
      continue;
    end if;

    select content::jsonb
      into detail_resp
    from net.http_get(
      url => format('https://api.splinterlands.com/tournaments/find?id=%s&username=%s', tid, organizer)
    )
    limit 1;

    start_date := coalesce(
      (detail_resp->>'start_date')::timestamptz,
      (item->>'start_date')::timestamptz
    );
    status := coalesce(
      detail_resp->>'status',
      detail_resp->>'current_round',
      item->>'status'
    );
    entrants := coalesce(
      (detail_resp->>'players_registered')::integer,
      (detail_resp->>'num_players')::integer,
      (item->>'players_registered')::integer
    );
    payouts := coalesce(
      detail_resp#>'{data,prizes,payouts}',
      detail_resp#>'{prizes,payouts}',
      item#>'{data,prizes,payouts}'
    );
    allowed_cards := coalesce(
      detail_resp#>'{data,allowed_cards}',
      item#>'{data,allowed_cards}'
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
      organizer,
      coalesce(item->>'name', detail_resp->>'name', tid),
      start_date,
      status,
      entrants,
      null,
      null,
      payouts,
      allowed_cards,
      item,
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

    for player in select * from jsonb_array_elements(players)
    loop
      prize_tokens := null; -- optional: future enhancement to parse ext_prize_info/prizes
      prize_text := coalesce(player->>'prize', player->>'player_prize', null);
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
        coalesce(player->>'player', player->>'username'),
        nullif(player->>'finish', '')::integer,
        prize_tokens,
        prize_text,
        player,
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
end;
$$;


-- Daily cron at 07:15 UTC to ingest organizer tournaments.
select
  cron.schedule(
    'tournament-ingest-daily',
    '15 7 * * *',
    $$select public.refresh_tournament_ingest('lorkus');$$
  );
