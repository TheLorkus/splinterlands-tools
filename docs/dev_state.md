# Dev State

## Architecture overview
- Entry point: `app.py` sets Streamlit config and routes to `pages/01_Home.py`; shared helpers live in `core/config.py` and `core/home.py`.
- UI pages:
  - `pages/01_Home.py`: hub with page links.
  - `pages/10_Brawl_Dashboard.py`: Brawl Assistant (guild history, player stats, trend charts).
  - `pages/20_Rewards_Tracker.py`: Rewards Tracker with optional Scholar mode, summaries, tournaments, and history.
  - `pages/30_Tournament_Series.py`: Series leaderboard + tournament configurator, Supabase ingest trigger, embeds `Tournament_Series.md`.
  - `pages/40_SPS_Analytics.py`: placeholder page.
- Modules:
  - `scholar_helper/services/api.py`: Splinterlands API client + parsing.
  - `scholar_helper/services/aggregation.py`: season filtering and totals.
  - `scholar_helper/services/storage.py`: Supabase PostgREST/RPC helpers.
  - `scholar_helper/services/brawl_dashboard.py`: brawl endpoints + helpers.
  - `series/leaderboard.py` and `series/tournament.py`: Tournament Series UI logic.
  - `features/*`: thin re-exports for page imports.
  - `scripts/*` and `scholar_helper/cli/*`: CLI sync/import/ingest utilities.
  - `supabase/*`: migrations + Edge function(s).

## Data flow and caching
- Brawl Dashboard: UI -> `features/brawl/service.py` -> `scholar_helper/services/brawl_dashboard.py` -> Splinterlands API (`/guilds/brawl_records`, `/tournaments/find_brawl`, `/guilds/list`). Cached via `st.cache_data` (TTL 300s for brawl calls, 86400s for guild list).
- Rewards Tracker: UI -> `features/scholar/service.py` -> `scholar_helper/services/api.py` -> Splinterlands API (`/settings`, `/season`, `/prices`, `/players/unclaimed_balance_history`, `/tournaments/completed`, `/tournaments/find`). Cached via `st.cache_data` (TTL 300s) plus in-memory `cachetools.TTLCache` (TTL 300s) inside the API module.
- Tournament Series: UI -> `series/*` -> `scholar_helper/services/storage.py` -> Supabase tables/views (`tournament_events`, `tournament_results`, `tournament_result_points`, `tournament_leaderboard_totals`). Falls back to live Splinterlands API via `fetch_hosted_tournaments` + `fetch_tournament_leaderboard` when Supabase has no rows.
- Supabase persistence: CLI/scripts (`scripts/season_sync.py`, `scholar_helper/cli/sync_supabase.py`, `scripts/import_season_history.py`) and the UI history tab read/write via `storage.py` (PostgREST). Tournament ingest is handled by the `tournament-ingest` Edge Function (scheduled via cron + manual UI trigger).

## Supabase configuration and schema
- Config sources: `.env` and Streamlit secrets (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, optional `SUPABASE_ANON_KEY`). `SUPABASE_SERVICE_KEY` is a legacy alias; prefer `SUPABASE_SERVICE_ROLE_KEY` in new setups (see `scholar_helper/services/storage.py`).
- Edge functions:
  - `supabase/functions/update-season-schedule` (calls Supabase Scheduler). Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, optional `SYNC_SEASON_ENDPOINT`, `SYNC_SCHEDULE_NAME`, `SYNC_FUNCTION_NAME`.
  - `supabase/functions/tournament-ingest` (Splinterlands ingest + upsert). Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
  - `season-sync` Edge function is referenced in migrations/README but not present in `supabase/functions`.
- Extensions and jobs (migrations): `pg_net`, `pg_cron`, `http`; cron jobs `season-sync-hourly`, `refresh-season-sync-cron`, and `tournament-ingest-frequent` (*/10 minutes, window set to 3 days).
- Tables/views/functions (from migrations and code usage):
  - Tables: `public.tournament_events`, `public.tournament_results`, `public.tournament_ingest_organizers`, `public.tournament_ingest_state`, `public.point_schemes`, `public.series_configs`, `public.season_rewards` (altered in migrations), `public.tournament_logs` (used by scripts).
  - Views: `public.tournament_result_points`, `public.tournament_leaderboard_totals`.
  - Functions: `public.refresh_tournament_ingest` (legacy), `public.normalize_prize_item`, `public.calculate_points_for_finish`, `public.insert_series_config_from_json`, `call_season_sync`, `call_update_season_schedule`, `public.call_tournament_ingest`.
  - RLS: public SELECT policies + service_role write policies for ingest/config tables (see `supabase/migrations/20251210223200_optimize_rls_policies.sql`).
- App write fields into `season_rewards`: `season_id`, `season_start`, `season_end`, `username`, `ranked_tokens`, `brawl_tokens`, `tournament_tokens`, `entry_fees_tokens`, `ranked_usd`, `brawl_usd`, `tournament_usd`, `entry_fees_usd`, `overall_usd`, `scholar_pct`, `payout_currency`, `scholar_payout` (see `scholar_helper/services/storage.py`, `scripts/import_season_history.py`).

## Implemented vs stubbed
- Implemented:
  - Streamlit hub + Brawl Assistant + Rewards Tracker (Scholar mode optional).
  - Tournament Series leaderboard/configurator with Supabase-backed data and API fallback.
  - Supabase ingest functions, views, and point scheme seed data.
  - CLI/scripts for season sync and CSV history import.
- Stubbed/placeholder:
  - SPS Analytics page is a placeholder (`pages/40_SPS_Analytics.py`).
  - Brawl persistence to Supabase is only planned (`planning_doc`).
  - `season-sync` Edge function code not in repo (only referenced in migrations/README).
  - UI fallback in `pages/30_Tournament_Series.py` returns "Helper not available" if `scholar_helper` isn't importable.

## TODOs and known bugs (top items)
(Only items documented in the repo are listed.)
1. Missing reward types/tokens not returned by the price feed can be excluded from totals (`project_summary`).
2. Payout table requires manual refresh for new usernames; no batching/scheduling (`project_summary`).
3. Persistence is gated behind Supabase credentials; no local fallback store (`project_summary`).
4. Historical imports require manual CSVs + service-role access (`project_summary`, `README.md`).
5. Entry fees are tracked but not subtracted from totals (`README.md`).
6. Brawl data persistence/ingest/scheduling is only planned (`planning_doc`).
7. SPS Analytics page is placeholder ("Coming soon") (`pages/40_SPS_Analytics.py`).
8. `season-sync` Edge function implementation is not in repo (only referenced) (`README.md`, `supabase/migrations/*`).
9. No migrations create `season_rewards` or `tournament_logs` tables; only alters/usages exist in repo (migrations + `scholar_helper/services/storage.py`).
10. README mentions uploading historical JSON, but no UI uploader is present; only the CSV import script exists (`README.md`, `pages/*`, `scripts/import_season_history.py`).

## Edge Function deployment (local CLI)
1. Install + login: `supabase login`
2. Link project: `supabase link --project-ref <project-ref>`
3. Deploy functions:
   - `supabase functions deploy tournament-ingest`
   - `supabase functions deploy update-season-schedule`
4. Set secrets:
   - `supabase secrets set SUPABASE_URL="https://<project-ref>.supabase.co" SUPABASE_SERVICE_ROLE_KEY="<service-role-key>"`
