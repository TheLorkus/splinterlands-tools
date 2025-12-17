create or replace function public.refresh_tournament_ingest(organizer text default null::text, max_age_days integer default 400)
returns void
language plpgsql
set search_path to 'public', 'pg_temp'
as $$
declare
  base_url text;
  service_key text;
  target_url text;
  headers jsonb := jsonb_build_object('Content-Type', 'application/json');
  body jsonb := jsonb_build_object('max_age_days', max_age_days, 'max_tournaments', 200);
begin
  select private.get_app_secret('supabase_url') into base_url;
  select private.get_app_secret('supabase_service_role_key') into service_key;

  if base_url is null then
    raise exception 'Missing supabase_url in private.app_secrets';
  end if;

  if service_key is null or service_key = '' then
    raise exception 'Missing supabase_service_role_key in private.app_secrets';
  end if;

  target_url := base_url || '/functions/v1/tournament-ingest';

  if organizer is not null and organizer <> '' then
    body := body || jsonb_build_object('organizer', organizer);
  end if;

  headers := headers || jsonb_build_object(
    'apikey', service_key,
    'Authorization', 'Bearer ' || service_key
  );

  perform net.http_post(
    url := target_url,
    headers := headers,
    body := body,
    timeout_milliseconds := 10000
  );
end;
$$;
