-- Adjust RLS policies to avoid per-row auth calls and overlapping permissive policies.

-- tournament_events
drop policy if exists tournament_events_write_service_role on public.tournament_events;
create policy tournament_events_insert_service_role
  on public.tournament_events
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');
create policy tournament_events_update_service_role
  on public.tournament_events
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');
create policy tournament_events_delete_service_role
  on public.tournament_events
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');

-- tournament_results
drop policy if exists tournament_results_write_service_role on public.tournament_results;
create policy tournament_results_insert_service_role
  on public.tournament_results
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');
create policy tournament_results_update_service_role
  on public.tournament_results
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');
create policy tournament_results_delete_service_role
  on public.tournament_results
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');

-- point_schemes
drop policy if exists point_schemes_write_service_role on public.point_schemes;
create policy point_schemes_insert_service_role
  on public.point_schemes
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');
create policy point_schemes_update_service_role
  on public.point_schemes
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');
create policy point_schemes_delete_service_role
  on public.point_schemes
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');

-- tournament_ingest_organizers
drop policy if exists tournament_ingest_organizers_write_service_role on public.tournament_ingest_organizers;
create policy tournament_ingest_organizers_insert_service_role
  on public.tournament_ingest_organizers
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');
create policy tournament_ingest_organizers_update_service_role
  on public.tournament_ingest_organizers
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');
create policy tournament_ingest_organizers_delete_service_role
  on public.tournament_ingest_organizers
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');

-- series_configs
drop policy if exists series_configs_write_service_role on public.series_configs;
create policy series_configs_insert_service_role
  on public.series_configs
  for insert
  to service_role
  with check ((select auth.role()) = 'service_role');
create policy series_configs_update_service_role
  on public.series_configs
  for update
  to service_role
  using ((select auth.role()) = 'service_role')
  with check ((select auth.role()) = 'service_role');
create policy series_configs_delete_service_role
  on public.series_configs
  for delete
  to service_role
  using ((select auth.role()) = 'service_role');
