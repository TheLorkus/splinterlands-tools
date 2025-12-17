-- Track tournament ingest runs per organizer and schedule edge-based ingestion.
create table if not exists public.tournament_ingest_state (
  organizer text primary key references public.tournament_ingest_organizers(username) on delete cascade,
  last_run_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  last_event_count integer,
  last_result_count integer,
  last_window_days integer,
  updated_at timestamptz default now()
);

alter table public.tournament_ingest_state enable row level security;

drop policy if exists tournament_ingest_state_select_public on public.tournament_ingest_state;
create policy tournament_ingest_state_select_public
  on public.tournament_ingest_state
  for select
  using (true);

drop policy if exists tournament_ingest_state_insert_service_role on public.tournament_ingest_state;
create policy tournament_ingest_state_insert_service_role
  on public.tournament_ingest_state
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');

drop policy if exists tournament_ingest_state_update_service_role on public.tournament_ingest_state;
create policy tournament_ingest_state_update_service_role
  on public.tournament_ingest_state
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');

drop policy if exists tournament_ingest_state_delete_service_role on public.tournament_ingest_state;
create policy tournament_ingest_state_delete_service_role
  on public.tournament_ingest_state
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');

create or replace function public.call_tournament_ingest(max_age_days integer default 3)
returns void
language sql
as $$
  select net.http_post(
    url := current_setting('supabase.url', true) || '/functions/v1/tournament-ingest',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'apikey', current_setting('supabase.service_role_key', true),
      'Authorization', 'Bearer ' || current_setting('supabase.service_role_key', true)
    ),
    body := jsonb_build_object('max_age_days', max_age_days),
    timeout_milliseconds := 10000
  );
$$;

do $$
begin
  if exists (select 1 from cron.job where jobname = 'tournament-ingest-frequent') then
    perform cron.unschedule('tournament-ingest-frequent');
  end if;
  if exists (select 1 from cron.job where jobname = 'tournament-ingest-daily') then
    perform cron.unschedule('tournament-ingest-daily');
  end if;
end;
$$;

select cron.schedule(
  'tournament-ingest-frequent',
  '*/10 * * * *',
  $$ select public.call_tournament_ingest(3); $$
);
