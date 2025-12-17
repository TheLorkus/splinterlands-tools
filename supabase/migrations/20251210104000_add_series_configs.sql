create table if not exists public.series_configs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  organizer text not null,
  point_scheme text not null default 'balanced',
  include_ids text[] default null,
  exclude_ids text[] default null,
  include_after timestamptz,
  include_before timestamptz,
  visibility text not null default 'public',
  note text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.series_configs enable row level security;

drop policy if exists series_configs_select_public on public.series_configs;
create policy series_configs_select_public
  on public.series_configs
  for select
  using (true);

drop policy if exists series_configs_write_service_role on public.series_configs;
create policy series_configs_write_service_role
  on public.series_configs
  for all
  to authenticated, service_role
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Index for organizer lookups.
create index if not exists series_configs_organizer_idx on public.series_configs (organizer);
