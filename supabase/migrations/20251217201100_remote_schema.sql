drop extension if exists "pg_net";

create schema if not exists "private";

create extension if not exists "pg_net" with schema "public";

drop policy "tournament_ingest_state_delete_service_role" on "public"."tournament_ingest_state";

drop policy "tournament_ingest_state_insert_service_role" on "public"."tournament_ingest_state";

drop policy "tournament_ingest_state_select_public" on "public"."tournament_ingest_state";

drop policy "tournament_ingest_state_update_service_role" on "public"."tournament_ingest_state";

revoke delete on table "public"."tournament_ingest_state" from "anon";

revoke insert on table "public"."tournament_ingest_state" from "anon";

revoke references on table "public"."tournament_ingest_state" from "anon";

revoke select on table "public"."tournament_ingest_state" from "anon";

revoke trigger on table "public"."tournament_ingest_state" from "anon";

revoke truncate on table "public"."tournament_ingest_state" from "anon";

revoke update on table "public"."tournament_ingest_state" from "anon";

revoke delete on table "public"."tournament_ingest_state" from "authenticated";

revoke insert on table "public"."tournament_ingest_state" from "authenticated";

revoke references on table "public"."tournament_ingest_state" from "authenticated";

revoke select on table "public"."tournament_ingest_state" from "authenticated";

revoke trigger on table "public"."tournament_ingest_state" from "authenticated";

revoke truncate on table "public"."tournament_ingest_state" from "authenticated";

revoke update on table "public"."tournament_ingest_state" from "authenticated";

revoke delete on table "public"."tournament_ingest_state" from "service_role";

revoke insert on table "public"."tournament_ingest_state" from "service_role";

revoke references on table "public"."tournament_ingest_state" from "service_role";

revoke select on table "public"."tournament_ingest_state" from "service_role";

revoke trigger on table "public"."tournament_ingest_state" from "service_role";

revoke truncate on table "public"."tournament_ingest_state" from "service_role";

revoke update on table "public"."tournament_ingest_state" from "service_role";

alter table "public"."tournament_ingest_state" drop constraint "tournament_ingest_state_organizer_fkey";

drop function if exists "public"."call_tournament_ingest"(max_age_days integer);

alter table "public"."tournament_ingest_state" drop constraint "tournament_ingest_state_pkey";

drop index if exists "public"."tournament_ingest_state_pkey";

drop table "public"."tournament_ingest_state";


  create table "private"."app_secrets" (
    "name" text not null,
    "value" text not null
      );



  create table "public"."tournament_logs" (
    "username" text not null,
    "tournament_id" text not null,
    "name" text,
    "start_date" timestamp with time zone,
    "entry_fee_token" text,
    "entry_fee_amount" numeric,
    "rewards" jsonb,
    "raw" jsonb,
    "inserted_at" timestamp with time zone default now()
      );


alter table "public"."tournament_logs" enable row level security;

alter table "public"."season_rewards" add column "brawl_tokens" jsonb;

alter table "public"."season_rewards" add column "brawl_usd" numeric;

alter table "public"."season_rewards" add column "entry_fees_tokens" jsonb;

alter table "public"."season_rewards" add column "entry_fees_usd" numeric;

alter table "public"."season_rewards" add column "overall_usd" numeric;

alter table "public"."season_rewards" add column "payout_currency" text;

alter table "public"."season_rewards" add column "ranked_tokens" jsonb;

alter table "public"."season_rewards" add column "ranked_usd" numeric;

alter table "public"."season_rewards" add column "scholar_pct" bigint;

alter table "public"."season_rewards" add column "season_id" integer not null;

alter table "public"."season_rewards" add column "tournament_tokens" jsonb;

alter table "public"."season_rewards" add column "tournament_usd" numeric;

alter table "public"."season_rewards" add column "updated_at" timestamp with time zone default now();

alter table "public"."season_rewards" add column "username" text not null;

alter table "public"."season_rewards" enable row level security;

CREATE UNIQUE INDEX app_secrets_pkey ON private.app_secrets USING btree (name);

CREATE UNIQUE INDEX season_rewards_pkey ON public.season_rewards USING btree (season_id, username);

CREATE UNIQUE INDEX tournament_logs_pkey ON public.tournament_logs USING btree (tournament_id, username);

alter table "private"."app_secrets" add constraint "app_secrets_pkey" PRIMARY KEY using index "app_secrets_pkey";

alter table "public"."season_rewards" add constraint "season_rewards_pkey" PRIMARY KEY using index "season_rewards_pkey";

alter table "public"."tournament_logs" add constraint "tournament_logs_pkey" PRIMARY KEY using index "tournament_logs_pkey";

set check_function_bodies = off;

CREATE OR REPLACE FUNCTION private.get_app_secret(secret_name text)
 RETURNS text
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
  select value from private.app_secrets where name = secret_name limit 1;
$function$
;

CREATE OR REPLACE FUNCTION public.call_season_sync()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  base_url text;
  service_key text;
  target_url text;
  headers jsonb;
begin
  select private.get_app_secret('supabase_url') into base_url;
  select private.get_app_secret('supabase_service_role_key') into service_key;

  if base_url is null or service_key is null then
    raise exception 'Missing supabase_url or supabase_service_role_key in private.app_secrets';
  end if;

  target_url := base_url || '/functions/v1/season-sync';
  headers := jsonb_build_object(
    'Content-Type', 'application/json',
    'Authorization', 'Bearer ' || service_key
  );

  perform net.http_post(
    url := target_url,
    headers := headers,
    body := jsonb_build_object('triggered_at', now()),
    timeout_milliseconds := 5000
  );
end;
$function$
;

CREATE OR REPLACE FUNCTION public.call_update_season_schedule()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  base_url text;
  service_key text;
  target_url text;
  headers jsonb;
begin
  select private.get_app_secret('supabase_url') into base_url;
  select private.get_app_secret('supabase_service_role_key') into service_key;

  if base_url is null or service_key is null then
    raise exception 'Missing supabase_url or supabase_service_role_key in private.app_secrets';
  end if;

  target_url := base_url || '/functions/v1/update-season-schedule';
  headers := jsonb_build_object(
    'Content-Type', 'application/json',
    'Authorization', 'Bearer ' || service_key
  );

  perform net.http_post(
    url := target_url,
    headers := headers,
    body := jsonb_build_object('triggered_at', now()),
    timeout_milliseconds := 5000
  );
end;
$function$
;

grant delete on table "public"."tournament_logs" to "anon";

grant insert on table "public"."tournament_logs" to "anon";

grant references on table "public"."tournament_logs" to "anon";

grant select on table "public"."tournament_logs" to "anon";

grant trigger on table "public"."tournament_logs" to "anon";

grant truncate on table "public"."tournament_logs" to "anon";

grant update on table "public"."tournament_logs" to "anon";

grant delete on table "public"."tournament_logs" to "authenticated";

grant insert on table "public"."tournament_logs" to "authenticated";

grant references on table "public"."tournament_logs" to "authenticated";

grant select on table "public"."tournament_logs" to "authenticated";

grant trigger on table "public"."tournament_logs" to "authenticated";

grant truncate on table "public"."tournament_logs" to "authenticated";

grant update on table "public"."tournament_logs" to "authenticated";

grant delete on table "public"."tournament_logs" to "service_role";

grant insert on table "public"."tournament_logs" to "service_role";

grant references on table "public"."tournament_logs" to "service_role";

grant select on table "public"."tournament_logs" to "service_role";

grant trigger on table "public"."tournament_logs" to "service_role";

grant truncate on table "public"."tournament_logs" to "service_role";

grant update on table "public"."tournament_logs" to "service_role";


  create policy "Season rewards managed by service role"
  on "public"."season_rewards"
  as permissive
  for all
  to service_role
using (true)
with check (true);



  create policy "Season rewards readable by anon"
  on "public"."season_rewards"
  as permissive
  for select
  to anon, authenticated
using (true);



  create policy "Tournament logs managed by service role"
  on "public"."tournament_logs"
  as permissive
  for all
  to service_role
using (true)
with check (true);



  create policy "Tournament logs readable by anon"
  on "public"."tournament_logs"
  as permissive
  for select
  to anon, authenticated
using (true);



