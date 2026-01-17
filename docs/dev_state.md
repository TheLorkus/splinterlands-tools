# Dev State

## 1) What this repo is
Splinterlands Tools is a Streamlit multipage app that combines a Brawl Assistant, Scholar Rewards Tracker, and Tournament Series tooling for Splinterlands data. The brawl tracker focuses on guild brawl history and player stats, with optional Supabase-backed persistence for tracked guilds. The repo also includes CLI utilities for ingesting brawl cycles, tournament results, and season snapshots into Supabase.

## 2) Current features
- Streamlit hub with Brawl Assistant, Rewards Tracker, and Tournament Series pages.
- Brawl Assistant: guild brawl history, per-player stats, and trend charts with optional database-backed reads and reward card annotations.
- Supabase persistence for brawls (cycles, player rows, reward annotations) and tournaments.
- CLI utilities for brawl ingest, brawl reward delegation, season sync, tournament refresh, and CSV import.
- Supabase migrations and Edge functions for tournament ingest and season schedule refresh.

## 3) Architecture overview (modules/services, data flow)
- UI layer: `app.py` routes to `pages/*` (Brawl Assistant lives in `pages/10_Brawl_Dashboard.py`).
- Brawl services:
  - `features/brawl/service.py` re-exports brawl helpers for UI pages.
  - `scholar_helper/services/brawl_dashboard.py` fetches live data from Splinterlands and computes stats.
  - `scholar_helper/services/brawl_persistence.py` reads/writes brawl tables in Supabase.
- Data flow for brawls:
  - Render: `pages/10_Brawl_Dashboard.py` -> `features/brawl/service.py` ->
    - Database path (tracked guilds with stored cycles): `fetch_brawl_cycles_supabase` + `build_history_df_from_cycles`, and `fetch_brawl_player_cycle_supabase` + `build_player_rows_from_supabase`.
    - Live API fallback: `fetch_guild_brawls` + `build_player_rows` (Splinterlands endpoints: `/guilds/brawl_records`, `/tournaments/find_brawl`).
  - Refresh: UI button or `scripts/ingest_brawls.py` -> `ingest_brawl_ids`.
  - Rewards: `fetch_brawl_rewards_supabase` returns reward annotations; admin-only writes via `scripts/brawl_rewards.py`.
- Caching: `st.cache_data` in `scholar_helper/services/brawl_dashboard.py` for brawl calls (TTL 300s) and guild list (TTL 86400s).

## 4) Key entrypoints (files + what they do)
- `app.py`: Streamlit entrypoint, routes to `pages/01_Home.py`.
- `pages/10_Brawl_Dashboard.py`: Brawl Assistant UI and data rendering.
- `features/brawl/service.py`: brawl feature API (thin re-export layer).
- `scholar_helper/services/brawl_dashboard.py`: live brawl API fetch + stats computation.
- `scholar_helper/services/brawl_persistence.py`: Supabase reads/writes for brawl cycles, players, rewards.
- `scripts/ingest_brawls.py`: CLI to ingest recent brawl cycles into Supabase.
- `scripts/brawl_rewards.py`: admin CLI to set or clear brawl reward card annotations.
- `supabase/migrations/20251222120000_brawl_persistence.sql`: schema for brawl tables and RLS.
- `docs/brawl_cli.md`: CLI usage for brawl ingest and rewards.

## 5) How to run locally (exact commands)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: configure Supabase secrets
cp .env.example .env

streamlit run app.py
```

## 6) How to run tests/lint/typecheck (exact commands, include pyright if present)
```bash
# Lint
ruff check .

# Format check
ruff format --check .
```
- Tests: no test runner or tests found in repo.
- Typecheck: no pyright config present; Pylance is used in the editor.

## 7) Configuration and secrets (env vars, where they are used, examples without real values)
- Local env: `.env` (see `.env.example`).
- Streamlit secrets: `.streamlit/secrets.toml` (used by `scholar_helper/services/storage.py`).

Example values (do not use real keys):
```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_SERVICE_KEY=<legacy-service-key>
SUPABASE_ANON_KEY=<anon-key>
DEFAULT_USERNAMES=lorkus,vorkus
TOURNAMENT_INGEST_MAX_TOURNAMENTS=200
SYNC_USERNAMES=lorkus,other_player
SYNC_SCHOLAR_PCT=50
SYNC_PAYOUT_CURRENCY=SPS
SYNC_SEASON_ENDPOINT=https://api.splinterlands.com/season?id=171
SYNC_SCHEDULE_NAME=season-sync
SYNC_FUNCTION_NAME=season-sync
```
Where used:
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`: Supabase access in `scholar_helper/services/storage.py`, brawl persistence, and CLI scripts.
- `DEFAULT_USERNAMES`: fallback organizers for tournament ingest in `scholar_helper/services/storage.py`.
- `TOURNAMENT_INGEST_MAX_TOURNAMENTS`: tournament ingest limit in `scholar_helper/services/storage.py`.
- `SYNC_*`: season sync scripts and `supabase/functions/update-season-schedule`.

## 8) Data/storage (DB tables, files, caches)
- Supabase tables for brawls: `tracked_guilds`, `brawl_cycles`, `brawl_player_cycle`, `brawl_rewards`.
- Brawl tables are defined in `supabase/migrations/20251222120000_brawl_persistence.sql` with RLS tied to tracked guilds.
- Rewards tracker and tournament tables are defined in other Supabase migrations (see `supabase/migrations`).
- Caches: `st.cache_data` in `scholar_helper/services/brawl_dashboard.py` (brawl APIs and guild list).
- Data files: CSV imports for season history are expected under `data/` (see `scripts/import_season_history.py`).

## 9) Deployments (Render/Fly/etc if present, how it is deployed)
- Supabase Edge functions:
  - `supabase/functions/tournament-ingest` (ingests tournaments).
  - `supabase/functions/update-season-schedule` (updates season sync schedule).
- Supabase migrations live under `supabase/migrations/`.
- CI: GitHub Actions runs ruff (`.github/workflows/ruff.yml`).
- No Streamlit hosting configuration (Render/Fly/Streamlit Cloud) is defined in this repo.

## 10) Known issues / tech debt (from TODOs, failing tests, comments)
- Entry fees are tracked but not subtracted from totals (README note).
- SPS Analytics page is a placeholder (`pages/40_SPS_Analytics.py`).
- Season-sync Edge function is referenced in migrations/README but not present in `supabase/functions`.
- Brawl ingestion is manual (UI button or CLI); no scheduler is present for brawl ingest.

## 11) Discord integration notes (based on existing code)
Brawl summary data producers:
- `scholar_helper/services/brawl_dashboard.fetch_guild_brawls` (live brawl cycles).
- `scholar_helper/services/brawl_persistence.fetch_brawl_cycles_supabase` + `build_history_df_from_cycles` (DB-backed cycles).
- `scholar_helper/services/brawl_dashboard.compute_player_stats` (windowed player stats).
- `scholar_helper/services/brawl_persistence.build_player_rows_from_supabase` and `build_player_rows` (per-player rows).
- `scholar_helper/services/brawl_persistence.fetch_brawl_rewards_supabase` (reward annotations).

Clean hook points:
- Webhook poster (push): after successful `ingest_brawl_ids` in `scholar_helper/services/brawl_persistence.py` or at the end of `scripts/ingest_brawls.py`, build a summary DataFrame and post to Discord.
- Slash-command bot (pull): build on `features/brawl/service.py` or directly call `fetch_brawl_cycles_supabase` + `build_history_df_from_cycles` for summary, and `compute_player_stats` for player stats, then format a response.

## 12) Open questions
- Where is the Streamlit app deployed (Streamlit Cloud, Render, etc.)?
- Should brawl ingestion be scheduled (cron/Edge function), and if so what cadence is desired?
- Is there a preferred Discord library or existing webhook endpoint for the brawl summary?
