create table if not exists public.tracked_guilds (
  guild_id text primary key,
  enabled boolean not null default true,
  label text null,
  created_at timestamptz not null default now()
);

create table if not exists public.brawl_cycles (
  brawl_id text primary key,
  guild_id text not null,
  tier int null,
  starts_at timestamptz null,
  ends_at timestamptz null,
  season_id int null,
  raw_summary jsonb not null,
  ingested_at timestamptz not null default now()
);

create index if not exists brawl_cycles_guild_ends_idx
  on public.brawl_cycles (guild_id, ends_at desc);

create index if not exists brawl_cycles_guild_ingested_idx
  on public.brawl_cycles (guild_id, ingested_at desc);

create table if not exists public.brawl_player_cycle (
  brawl_id text not null references public.brawl_cycles (brawl_id) on delete cascade,
  guild_id text not null,
  player text not null,
  frays_entered int null,
  battles_played int null,
  wins int null,
  losses int null,
  draws int null,
  submitted boolean null,
  raw jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (brawl_id, player)
);

create index if not exists brawl_player_cycle_guild_player_idx
  on public.brawl_player_cycle (guild_id, player);

create index if not exists brawl_player_cycle_guild_brawl_idx
  on public.brawl_player_cycle (guild_id, brawl_id);

create table if not exists public.brawl_rewards (
  brawl_id text not null references public.brawl_cycles (brawl_id) on delete cascade,
  guild_id text not null,
  player text not null,
  is_perfect boolean not null default false,
  card_text text null,
  foil text null,
  note text null,
  updated_at timestamptz not null default now(),
  primary key (brawl_id, player)
);

create index if not exists brawl_rewards_guild_player_idx
  on public.brawl_rewards (guild_id, player);

alter table public.tracked_guilds enable row level security;
alter table public.brawl_cycles enable row level security;
alter table public.brawl_player_cycle enable row level security;
alter table public.brawl_rewards enable row level security;

create policy "Tracked guilds readable"
  on public.tracked_guilds
  for select
  using (enabled = true);

create policy "Brawl cycles readable for tracked guilds"
  on public.brawl_cycles
  for select
  using (
    exists (
      select 1
      from public.tracked_guilds tg
      where tg.guild_id = brawl_cycles.guild_id
        and tg.enabled = true
    )
  );

create policy "Brawl player cycles readable for tracked guilds"
  on public.brawl_player_cycle
  for select
  using (
    exists (
      select 1
      from public.tracked_guilds tg
      where tg.guild_id = brawl_player_cycle.guild_id
        and tg.enabled = true
    )
  );

create policy "Brawl rewards readable for tracked guilds"
  on public.brawl_rewards
  for select
  using (
    exists (
      select 1
      from public.tracked_guilds tg
      where tg.guild_id = brawl_rewards.guild_id
        and tg.enabled = true
    )
  );
