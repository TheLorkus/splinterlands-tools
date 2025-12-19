
  create table "public"."tournament_ingest_state" (
    "organizer" text not null,
    "last_run_at" timestamp with time zone,
    "last_success_at" timestamp with time zone,
    "last_error" text,
    "last_event_count" integer,
    "last_result_count" integer,
    "last_window_days" integer,
    "updated_at" timestamp with time zone default now()
      );


alter table "public"."tournament_ingest_state" enable row level security;

CREATE UNIQUE INDEX tournament_ingest_state_pkey ON public.tournament_ingest_state USING btree (organizer);

alter table "public"."tournament_ingest_state" add constraint "tournament_ingest_state_pkey" PRIMARY KEY using index "tournament_ingest_state_pkey";

alter table "public"."tournament_ingest_state" add constraint "tournament_ingest_state_organizer_fkey" FOREIGN KEY (organizer) REFERENCES public.tournament_ingest_organizers(username) ON DELETE CASCADE not valid;

alter table "public"."tournament_ingest_state" validate constraint "tournament_ingest_state_organizer_fkey";

grant delete on table "public"."tournament_ingest_state" to "anon";

grant insert on table "public"."tournament_ingest_state" to "anon";

grant references on table "public"."tournament_ingest_state" to "anon";

grant select on table "public"."tournament_ingest_state" to "anon";

grant trigger on table "public"."tournament_ingest_state" to "anon";

grant truncate on table "public"."tournament_ingest_state" to "anon";

grant update on table "public"."tournament_ingest_state" to "anon";

grant delete on table "public"."tournament_ingest_state" to "authenticated";

grant insert on table "public"."tournament_ingest_state" to "authenticated";

grant references on table "public"."tournament_ingest_state" to "authenticated";

grant select on table "public"."tournament_ingest_state" to "authenticated";

grant trigger on table "public"."tournament_ingest_state" to "authenticated";

grant truncate on table "public"."tournament_ingest_state" to "authenticated";

grant update on table "public"."tournament_ingest_state" to "authenticated";

grant delete on table "public"."tournament_ingest_state" to "service_role";

grant insert on table "public"."tournament_ingest_state" to "service_role";

grant references on table "public"."tournament_ingest_state" to "service_role";

grant select on table "public"."tournament_ingest_state" to "service_role";

grant trigger on table "public"."tournament_ingest_state" to "service_role";

grant truncate on table "public"."tournament_ingest_state" to "service_role";

grant update on table "public"."tournament_ingest_state" to "service_role";


  create policy "tournament_ingest_state_delete_service_role"
  on "public"."tournament_ingest_state"
  as permissive
  for delete
  to service_role
using ((( SELECT auth.role() AS role) = 'service_role'::text));



  create policy "tournament_ingest_state_insert_service_role"
  on "public"."tournament_ingest_state"
  as permissive
  for insert
  to service_role
with check ((( SELECT auth.role() AS role) = 'service_role'::text));



  create policy "tournament_ingest_state_select_public"
  on "public"."tournament_ingest_state"
  as permissive
  for select
  to public
using (true);



  create policy "tournament_ingest_state_update_service_role"
  on "public"."tournament_ingest_state"
  as permissive
  for update
  to service_role
using ((( SELECT auth.role() AS role) = 'service_role'::text))
with check ((( SELECT auth.role() AS role) = 'service_role'::text));



