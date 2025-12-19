create extension if not exists pgcrypto;

create table if not exists public.reward_cards (
  reward_card_id uuid primary key default gen_random_uuid(),
  name text not null,
  enabled boolean not null default true,
  sort_order int null,
  notes text null,
  created_at timestamptz not null default now()
);

create unique index if not exists reward_cards_name_key
  on public.reward_cards (name);

create table if not exists public.tournament_rewards (
  tournament_id text not null,
  player text not null,
  reward_card_id uuid null references public.reward_cards (reward_card_id),
  note text null,
  updated_at timestamptz not null default now(),
  primary key (tournament_id, player)
);

create index if not exists tournament_rewards_tournament_id_idx
  on public.tournament_rewards (tournament_id);

create index if not exists tournament_rewards_player_idx
  on public.tournament_rewards (player);
