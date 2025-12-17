create table if not exists public.tournament_events (
  tournament_id text primary key,
  organizer text,
  name text,
  start_date timestamptz,
  status text,
  entrants integer,
  entry_fee_token text,
  entry_fee_amount numeric,
  payouts jsonb,
  allowed_cards jsonb,
  raw_list jsonb,
  raw_detail jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists tournament_events_start_date_idx on public.tournament_events (start_date);
create index if not exists tournament_events_organizer_idx on public.tournament_events (organizer);

create table if not exists public.tournament_results (
  tournament_id text not null references public.tournament_events(tournament_id) on delete cascade,
  player text not null,
  finish integer,
  prize_tokens jsonb,
  prize_text text,
  raw jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  primary key (tournament_id, player)
);

create index if not exists tournament_results_finish_idx on public.tournament_results (finish);

alter table public.tournament_events enable row level security;
alter table public.tournament_results enable row level security;

drop policy if exists tournament_events_select_public on public.tournament_events;
create policy tournament_events_select_public
  on public.tournament_events
  for select
  using (true);

drop policy if exists tournament_events_write_service_role on public.tournament_events;
create policy tournament_events_write_service_role
  on public.tournament_events
  for all
  to authenticated, service_role
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

drop policy if exists tournament_results_select_public on public.tournament_results;
create policy tournament_results_select_public
  on public.tournament_results
  for select
  using (true);

drop policy if exists tournament_results_write_service_role on public.tournament_results;
create policy tournament_results_write_service_role
  on public.tournament_results
  for all
  to authenticated, service_role
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
