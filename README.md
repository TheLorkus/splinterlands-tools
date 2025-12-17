# Splinterlands Tools

Streamlit toolkit combining the Scholar Rewards Tracker and Brawl Assistant to track Splinterlands account performance, split rewards with a scholar, and sync snapshots to Supabase.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Python version: see `runtime.txt` (3.11.14).

## Configuration

- Copy `.env.example` to `.env` and set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (or `SUPABASE_ANON_KEY`) to enable persistence.
- Default username: `lorkus` (edit in the UI).
- Upload historical JSON (`{"rewards": [...], "tournaments": [...]}`) to augment API data.

## Scheduled sync to Supabase

- CLI: `python -m scholar_helper.cli.sync_supabase --usernames lorkus,other_player`
- Runs the same fetch/aggregate logic and upserts to Supabase; needs `SUPABASE_URL` + key in env.
- To automate, point a cron/GitHub Action/runner at the CLI. Supabase Scheduled Functions can be used as a cron trigger; wrap this command in a containerized runner if you want it to live next to your Supabase project.
- Supabase automation: migrations create `call_season_sync()` + pg_cron job `season-sync-hourly` and `call_update_season_schedule()` + `refresh-season-sync-cron` that POST the Edge functions.
- Deploy the Edge Functions: `supabase functions deploy season-sync` (existing) and `supabase functions deploy update-season-schedule`; set the secret `SUPABASE_SERVICE_ROLE_KEY=<service-role-key>`.
- The `update-season-schedule` function refreshes the Supabase Scheduler entry named `season-sync` to run 10 minutes before the current season ends (default season endpoint: `https://api.splinterlands.com/season?id=171`). Invoke it once after deploy (`supabase functions invoke update-season-schedule --no-verify-jwt`) or wait for the midnight cron to seed the schedule.

## Brawl dashboard

Splinterlands Tools loads a “Brawl Assistant” landing page (it loads first) that mirrors the standalone Splinterlands Brawl Dashboard repo: enter a guild ID (defaulting to your guild) and use the multi-tab layout (Brawl history, Player stats, Guild trends) to see recent cycles, drill into individual tournaments, and compare player win rates. The Scholar rewards tracker remains available as the second page. The Brawl Assistant leverages `scholar_helper.services.brawl_dashboard` and can be extended with Supabase persistence once the brawl schema is finalized.
-## Import historical season snapshots

- Both the app and importer require the `SUPABASE_SERVICE_ROLE_KEY` (not just `SUPABASE_ANON_KEY`) so they can read/write `public.season_rewards`; configure that secret in Streamlit Cloud and your `.env` file to keep the history tab working.
- You can optionally include ISO8601 `season_start`/`season_end` columns, but if they’re missing the script will leave them blank by default; pass `--fetch-season-window` (and optionally `--season-api`) to pull ranges from Splinterlands when you want them filled. The schema accepts NULL so the UI simply renders `-` when dates are unavailable.
- Export the CSV into `data/history-lorkus.csv` (or any repo-relative path) so you can reference it consistently. Run the helper script from the repository root with the Supabase URL/key, the CSV path, and any mappings your headers require:

  ```bash
  SUPABASE_URL=https://<your-ref>.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=<your-service-role> \
    python scripts/import_season_history.py data/history-lorkus.csv \
      --mapping season_id=Season \
      --mapping scholar_payout="Scholar share" \
      --mapping payout_currency=Payment \
      --mapping ranked_tokens=Survival+Modern \
      --mapping brawl_tokens=Brawl \
      --mapping tournament_tokens=Tournaments
  ```

  Tweak the `--mapping` arguments whenever your CSV headers differ from the table columns, override `--default-token` if the numeric values belong to a different symbol, and add `--dry-run` to preview the payloads before hitting Supabase.

- Need more control? Pass `--fetch-season-window` if you want the importer to reach out to `--season-api` (default `https://api.splinterlands.com/season?id={season_id}`) whenever the CSV lacks start/end columns.

- The script posts batches of rows to `public.season_rewards`, so duplicates merge with the existing values. After the import, confirm the new rows with `select * from public.season_rewards where username='lorkus' order by season_id desc limit 20;` in Supabase SQL or via the Scholar History tab.

- To import history for another username (e.g., `vorkus`), run the same script with that CSV and the `--username vorkus` flag so the records land under the correct account.
- `Scholar share` maps to the `scholar_payout` column, preserving the absolutely-paid SPS amount rather than overwriting the percentage helper (`scholar_pct`). Point the script at that column (`--mapping scholar_payout="Scholar share"`) so you keep the actual payout values available for the Scholar History tab.

## Notes

- API fetches are cached for 5 minutes and can be manually refreshed.
- Entry fees are tracked but not subtracted from totals.
- Season boundaries come from the `/settings` endpoint (start = previous season end, end = current season end).
