alter table public.reward_cards enable row level security;
alter table public.tournament_rewards enable row level security;

create policy "Reward cards readable"
  on public.reward_cards
  for select
  to anon, authenticated
  using (true);

create policy "Tournament rewards readable"
  on public.tournament_rewards
  for select
  to anon, authenticated
  using (true);
