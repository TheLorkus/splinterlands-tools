-- Reduce tournament ingest cron window to 3 days to keep daily runs quick.
do $$
declare
  job_exists boolean;
begin
  select exists(select 1 from cron.job where jobid = 6) into job_exists;
  if job_exists then
    perform cron.alter_job(6, command => 'select public.refresh_tournament_ingest(null::text, 3);');
  else
    perform cron.schedule(
      'tournament-ingest-daily',
      '15 7 * * *',
      'select public.refresh_tournament_ingest(null::text, 3);'
    );
  end if;
end
$$;
