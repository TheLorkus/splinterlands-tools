-- Ensure tournament views run with caller's privileges (respect RLS).
alter view public.tournament_result_points set (security_invoker = true);
alter view public.tournament_leaderboard_totals set (security_invoker = true);

-- Pin function search_path to avoid role-mutability warnings.
alter function public.calculate_points_for_finish(integer, text) set search_path to public, pg_temp;
alter function public.normalize_prize_item(jsonb) set search_path to public, pg_temp;
alter function public.refresh_tournament_ingest(text, integer) set search_path to public, pg_temp;
alter function public.refresh_tournament_ingest(text) set search_path to public, pg_temp;
