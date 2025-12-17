-- Add a tournament name string filter to series configs for reproducible search.
alter table public.series_configs
  add column if not exists name_filter text;

create index if not exists series_configs_name_filter_idx
  on public.series_configs (name_filter);
