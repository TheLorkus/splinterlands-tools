create or replace function call_season_sync()
returns void
language sql
as $$
  select net.http_post(
    url := 'https://anaylgmrsgsuxjrcbazf.supabase.co/functions/v1/season-sync',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'apikey', '<YOUR_ANON_OR_SERVICE_KEY>',
      'Authorization', 'Bearer <YOUR_SERVICE_ROLE_KEY>'
    ),
    body := jsonb_build_object('triggered_at', now()),
    timeout_milliseconds := 5000
  );
$$;