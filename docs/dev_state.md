# Dev State

## Architecture overview
- Entry point: `app.py` sets Streamlit config and routes to `pages/01_Home.py`; shared helpers live in `core/config.py` and `core/home.py`.
- UI pages:
  - `pages/01_Home.py`: hub with page links.
  - `pages/10_Brawl_Dashboard.py`: Brawl Assistant (guild history, player stats, trend charts).
  - `pages/20_Rewards_Tracker.py`: Rewards Tracker with optional Scholar mode, summaries, tournaments, and history. Snapshot saves now reuse the same fetched reward/tournament rows shown in the UI (no refetch drift), and the history tab re-values token buckets with current prices when available.
  - `pages/30_Tournament_Series.py`: Series leaderboard + tournament configurator, Supabase ingest trigger, embeds `Tournament_Series.md`.
  - `pages/40_SPS_Analytics.py`: placeholder page.
- Modules:
  - `scholar_helper/services/api.py`: Splinterlands API client + parsing.
  - `scholar_helper/services/aggregation.py`: season filtering and totals.
  - `scholar_helper/services/storage.py`: Supabase PostgREST/RPC helpers, including tournament reward card catalog and per-tournament delegation fetch helpers.
  - `scholar_helper/services/brawl_dashboard.py`: brawl endpoints + helpers.
  - `scholar_helper/services/brawl_persistence.py`: Supabase brawl persistence (tracked guild checks, ingest, reads).
  - `series/leaderboard.py` and `series/tournament.py`: Tournament Series UI logic.
  - `features/*`: thin re-exports for page imports.
  - `scripts/*` and `scholar_helper/cli/*`: CLI sync/import/ingest utilities.
  - `supabase/*`: migrations + Edge function(s).

## Data flow and caching
- Brawl Dashboard: UI -> `features/brawl/service.py` -> Supabase-first reads for tracked guilds (`tracked_guilds`, `brawl_cycles`, `brawl_player_cycle`, `brawl_rewards`) with fallback to live Splinterlands API (`/guilds/brawl_records`, `/tournaments/find_brawl`, `/guilds/list`). Cached via `st.cache_data` (TTL 300s for live brawl calls, 86400s for guild list). Manual refresh triggers ingestion via service-role key; drill-down shows reward card text with foil styling when rewards exist.
- Rewards Tracker: UI -> `features/scholar/service.py` -> `scholar_helper/services/api.py` -> Splinterlands API (`/settings`, `/season`, `/prices`, `/players/unclaimed_balance_history`, `/tournaments/completed`, `/tournaments/find`). Cached via `st.cache_data` (TTL 300s) plus in-memory `cachetools.TTLCache` (TTL 300s) inside the API module. Snapshot saves use the already-fetched rows per user to avoid stale writes; history rows are displayed with USD re-derived from stored token buckets when price data is available.
- Tournament Series: UI -> `series/*` -> `scholar_helper/services/storage.py` -> Supabase tables/views (`tournament_events`, `tournament_results`, `tournament_result_points`, `tournament_leaderboard_totals`). Falls back to live Splinterlands API via `fetch_hosted_tournaments` + `fetch_tournament_leaderboard` when Supabase has no rows. When the organizer is "lorkus", the series leaderboard and per-tournament leaderboard also display delegated reward cards pulled from the reward card catalog and tournament reward annotations, ordered by tournament_id across the series window.
- Supabase persistence: CLI/scripts (`scripts/season_sync.py`, `scholar_helper/cli/sync_supabase.py`, `scripts/import_season_history.py`) and the UI history tab read/write via `storage.py` (PostgREST). Tournament ingest is handled by the `tournament-ingest` Edge Function (scheduled via cron + manual UI trigger).

## Supabase configuration and schema
- Config sources: `.env` and Streamlit secrets (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, optional `SUPABASE_ANON_KEY`). `SUPABASE_SERVICE_KEY` is a legacy alias; prefer `SUPABASE_SERVICE_ROLE_KEY` in new setups (see `scholar_helper/services/storage.py`).
- Edge functions:
  - `supabase/functions/update-season-schedule` (calls Supabase Scheduler). Env: `SUPABASE_URL`, optional `SYNC_SEASON_ENDPOINT`, `SYNC_SCHEDULE_NAME`, `SYNC_FUNCTION_NAME`. Uses the incoming `Authorization` header for Supabase auth.
  - `supabase/functions/tournament-ingest` (Splinterlands ingest + upsert). Env: `SUPABASE_URL`. Uses the incoming `Authorization` header for Supabase auth.
  - `season-sync` Edge function is referenced in migrations/README but not present in `supabase/functions`.
- Extensions and jobs (migrations): `pg_net`, `pg_cron`, `http`; cron jobs `season-sync-hourly`, `refresh-season-sync-cron`, and `tournament-ingest-frequent` (*/10 minutes, window set to 3 days). RLS is enabled on `reward_cards` and `tournament_rewards` with public read policies.
- Tables/views/functions (from migrations and code usage):
  - Tables: `public.tracked_guilds`, `public.brawl_cycles`, `public.brawl_player_cycle`, `public.brawl_rewards`, `public.tournament_events`, `public.tournament_results`, `public.tournament_ingest_organizers`, `public.tournament_ingest_state`, `public.point_schemes`, `public.series_configs`, `public.season_rewards` (altered in migrations), `public.tournament_logs` (used by scripts), `public.reward_cards`, `public.tournament_rewards`.
  - Views: `public.tournament_result_points`, `public.tournament_leaderboard_totals`.
  - Functions: `public.refresh_tournament_ingest` (legacy), `public.normalize_prize_item`, `public.calculate_points_for_finish`, `public.insert_series_config_from_json`, `call_season_sync`, `call_update_season_schedule`, `public.call_tournament_ingest`.
  - RLS: public SELECT policies + service_role write policies for ingest/config tables (see `supabase/migrations/20251210223200_optimize_rls_policies.sql`).
- App write fields into `season_rewards`: `season_id`, `season_start`, `season_end`, `username`, `ranked_tokens`, `brawl_tokens`, `tournament_tokens`, `entry_fees_tokens`, `ranked_usd`, `brawl_usd`, `tournament_usd`, `entry_fees_usd`, `overall_usd`, `scholar_pct`, `payout_currency`, `scholar_payout` (see `scholar_helper/services/storage.py`, `scripts/import_season_history.py`).

## Implemented vs stubbed
- Implemented:
  - Streamlit hub + Brawl Assistant + Rewards Tracker (Scholar mode optional).
  - Brawl persistence to Supabase for tracked guilds (cycles, player stats, reward annotations).
  - Tournament Series leaderboard/configurator with Supabase-backed data and API fallback.
  - Supabase ingest functions, views, and point scheme seed data.
  - CLI/scripts for season sync, CSV history import, and brawl ingest.
  - Tournament Series delegated card tracking: catalog-backed reward cards and per-tournament annotations, displayed read-only in series and per-event leaderboards for organizer "lorkus".
- Stubbed/placeholder:
  - SPS Analytics page is a placeholder (`pages/40_SPS_Analytics.py`).
  - `season-sync` Edge function code not in repo (only referenced in migrations/README).
  - UI fallback in `pages/30_Tournament_Series.py` returns "Helper not available" if `scholar_helper` isn't importable.

## TODOs and known bugs (top items)
(Only items documented in the repo are listed.)
5. Entry fees are tracked but not subtracted from totals (`README.md`).
6. Brawl ingest is manual only; no scheduler/cron is configured yet (`planning_doc`).
7. SPS Analytics page is placeholder ("Coming soon") (`pages/40_SPS_Analytics.py`).


## Edge Function deployment (local CLI)
1. Install + login: `supabase login`
2. Link project: `supabase link --project-ref <project-ref>`
3. Deploy functions:
   - `supabase functions deploy tournament-ingest`
   - `supabase functions deploy update-season-schedule`
4. Set secrets:
   - `supabase secrets set SUPABASE_URL="https://<project-ref>.supabase.co" SUPABASE_SERVICE_ROLE_KEY="<service-role-key>"`
