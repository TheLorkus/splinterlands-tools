-- Helper: drop-and-recreate a tiny JSON ingestion wrapper for series_configs.
create or replace function public.insert_series_config_from_json(payload jsonb)
returns public.series_configs
language plpgsql
set search_path to public, pg_temp
as $$
declare
  rec public.series_configs;
begin
  insert into public.series_configs (
    name,
    organizer,
    point_scheme,
    include_ids,
    exclude_ids,
    include_after,
    include_before,
    name_filter,
    qualification_cutoff,
    visibility,
    note
  )
  values (
    coalesce(nullif(payload->>'name', ''), '(name this config)'),
    payload->>'organizer',
    coalesce(nullif(payload->>'point_scheme', ''), 'balanced'),
    (
      select coalesce(array_agg(value::text), '{}')
      from jsonb_array_elements_text(coalesce(payload->'include_ids', '[]'::jsonb)) as t(value)
    ),
    (
      select coalesce(array_agg(value::text), '{}')
      from jsonb_array_elements_text(coalesce(payload->'exclude_ids', '[]'::jsonb)) as t(value)
    ),
    (payload->>'include_after')::timestamptz,
    (payload->>'include_before')::timestamptz,
    nullif(payload->>'name_filter', ''),
    nullif(payload->>'qualification_cutoff', '')::numeric,
    coalesce(nullif(payload->>'visibility', ''), 'public'),
    nullif(payload->>'note', '')
  )
  returning * into rec;

  return rec;
end;
$$;
