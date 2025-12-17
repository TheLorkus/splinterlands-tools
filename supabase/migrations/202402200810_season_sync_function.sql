create or replace function call_season_sync()
returns void
language sql
as $$
  select net.http_post(
    url := current_setting('supabase.url', true) || '/functions/v1/season-sync',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer ' || current_setting('supabase.service_role_key', true)
    ),
    body := jsonb_build_object('triggered_at', now())
  );
$$;
