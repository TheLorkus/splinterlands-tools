## Objective
Add the Splinterlands Brawl Dashboard playback into the Splinterlands Tools app as a second Streamlit tab, reusing the existing layout while syncing the new feature with Supabase persistence so both dashboards share a single backend.

## Step 1: Understand the Brawl Dashboard repo
- Clone or review `https://github.com/TheLorkus/splinterlands-brawl-dashboard` and document its data flow, UI components, and any third-party requirements (models, APIs, data caches, tokens).  
- Identify which parts are ready-to-use (e.g., API wrappers, aggregation logic, page layout) and which rely on unique data sources or credentials that need to be consolidated with Splinterlands Tools.

## Step 2: Define the new page structure
- In `app.py`, add a second tab or navigation item for “Brawl dashboard” (or similar). Extract the existing components into helper functions so the tabs don’t grow unwieldy.  
- Instead of extending a single screen, turn the UI into a multi-page experience: make “Brawl Assistant” the landing page, then let the user switch to the Scholar rewards tracker as the second page (the deck on the right can remain unchanged). Extract the page logic into functions to keep the code modular.
- Reuse shared services (e.g., price loader, API clients) where possible; extract common utilities into `scholar_helper.services` modules.  
- Plan the UX so both tabs offer consistent inputs (usernames, filters) and include a shared history/persistence trigger if relevant.

## Step 3: Identify Supabase tables/columns
- From the Brawl dashboard’s data model, design Supabase tables to store per-user/per-season brawl stats, match logs, or aggregated payouts. Determine data types, indexes, and primary keys that mirror the current season reporting tables.  
- Write migrations (under `supabase/migrations/`) to create these tables, any required functions (upsert RPCs or triggers), and records referencing both dashboards if needed.  
- Ensure Supabase policies/keys (service role for ingestion, anon for read-only history) align with the Splinterlands Tools setup.

## Step 4: Hook import/sync code into the new page
- Implement a service in `scholar_helper.services` that fetches brawl data (reusing the logic from the other repo) and persists it with Supabase updates similar to `upsert_season_totals`.  
- Add new CLI/scheduler hooks if automation is needed (e.g., reuse `scripts/season_sync.py` as a template).  
- Ensure the new page renders data from Supabase when available, falling back to API calls otherwise; unify error handling/logging with the existing storage helpers.

## Step 5: Sync deployment and docs
- Update `README.md`, `planning_doc`, and `project_summary` to describe the dual-tab workflow, the new Supabase tables, and any deployment steps.  
- Adjust Streamlit settings or secrets to expose any new URLs/keys needed by the Brawl dashboard slice.  
- Add tests or interactive checks to validate both tabs before pushing to production.

## Step 6: Merge & validate
- Add `merge_steps.md` to source control (done) and schedule a full integration test: run the Streamlit app, verify both tabs load, and confirm Supabase tables ingest/display the expected rows.  
- After successful validation, document any remaining TODOs in `planning_doc` or a new release note, then merge the changes.
