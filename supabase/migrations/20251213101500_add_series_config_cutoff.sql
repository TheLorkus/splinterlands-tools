-- Add an optional qualification cutoff (points threshold) to series_configs.
alter table public.series_configs
  add column if not exists qualification_cutoff numeric;

-- Convenience index if you later filter by cutoff.
create index if not exists series_configs_cutoff_idx
  on public.series_configs (qualification_cutoff);
