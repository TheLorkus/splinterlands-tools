select cron.schedule(
  'season-sync-hourly',              -- job name
  '0 * * * *',                       -- run at minute 0 every hour
  $$ select call_season_sync(); $$   -- SQL to execute
);
