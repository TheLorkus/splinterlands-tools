select cron.schedule(
  'refresh-season-sync-cron',                -- job name
  '0 0 * * *',                               -- run daily at 00:00 UTC
  $$ select call_update_season_schedule(); $$ -- SQL to execute
);
