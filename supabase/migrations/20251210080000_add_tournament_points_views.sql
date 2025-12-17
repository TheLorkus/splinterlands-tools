-- Helper to translate placements into points using the configured scheme.
create or replace function public.calculate_points_for_finish(
  finish integer,
  scheme_slug text default 'balanced'
)
returns numeric
language plpgsql
as $$
declare
  scheme record;
  rule jsonb;
  min_place integer;
  max_place integer;
  points numeric := null;
begin
  if scheme_slug is null then
    scheme_slug := 'balanced';
  end if;

  select mode, base_points, dnp_points, rules
    into scheme
  from public.point_schemes
  where slug = scheme_slug
  limit 1;

  if not found then
    return null;
  end if;

  if finish is null then
    return scheme.dnp_points;
  end if;

  for rule in select * from jsonb_array_elements(scheme.rules)
  loop
    min_place := (rule ->> 'min')::integer;
    max_place := nullif(rule ->> 'max', '')::integer;
    if finish >= min_place and (max_place is null or finish <= max_place) then
      if scheme.mode = 'multiplier' then
        points := scheme.base_points * coalesce((rule ->> 'multiplier')::numeric, 1);
      else
        points := scheme.base_points + coalesce((rule ->> 'points')::numeric, 0);
      end if;
      exit;
    end if;
  end loop;

  if points is null then
    points := scheme.dnp_points;
  end if;

  return points;
end;
$$ stable;


-- Points per player per tournament (multiple schemes for flexibility).
create or replace view public.tournament_result_points as
select
  e.organizer,
  e.tournament_id,
  e.name,
  e.start_date,
  e.status,
  r.player,
  r.finish,
  r.prize_tokens,
  r.prize_text,
  calculate_points_for_finish(r.finish, 'balanced') as points_balanced,
  calculate_points_for_finish(r.finish, 'performance') as points_performance,
  calculate_points_for_finish(r.finish, 'participation') as points_participation
from public.tournament_results r
join public.tournament_events e on e.tournament_id = r.tournament_id;


-- Rollup totals per organizer + player (default balanced points).
create or replace view public.tournament_leaderboard_totals as
select
  organizer,
  player,
  count(*) as events_played,
  sum(points_balanced) as points_balanced,
  sum(points_performance) as points_performance,
  sum(points_participation) as points_participation,
  avg(finish) as avg_finish,
  min(finish) as best_finish,
  count(*) filter (where finish between 1 and 3) as podiums,
  max(start_date) as last_event_date
from public.tournament_result_points
group by organizer, player;
