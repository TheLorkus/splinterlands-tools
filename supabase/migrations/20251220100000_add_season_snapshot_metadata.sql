-- Add snapshot coverage metadata for per-account season rewards snapshots.
alter table public.season_rewards
    add column if not exists snapshot_reward_count integer,
    add column if not exists snapshot_tournament_count integer,
    add column if not exists snapshot_last_reward_at timestamptz,
    add column if not exists snapshot_last_tournament_at timestamptz,
    add column if not exists snapshot_captured_at timestamptz default now();

-- Ensure per-account season uniqueness in username-first order for lookups.
create unique index if not exists season_rewards_username_season_idx
    on public.season_rewards (username, season_id);
