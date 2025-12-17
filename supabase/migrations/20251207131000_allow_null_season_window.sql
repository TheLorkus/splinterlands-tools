alter table public.season_rewards
  alter column season_start drop not null;

alter table public.season_rewards
  alter column season_end drop not null;
