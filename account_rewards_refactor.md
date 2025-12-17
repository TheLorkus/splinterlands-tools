# Rewards Tracker Refactor Plan (Account-first, Scholar Mode Optional)

## Goals
- Make the experience account-centric by default (“Rewards Tracker”).
- Keep all existing scholar features, but gate them behind a simple “Scholar mode” toggle (checkbox or radio).
- Avoid schema changes unless absolutely necessary; prefer derived/optional behavior.
- Reduce cognitive load in the UI by hiding scholar-only controls/history until enabled.

## UX / Behavior
- **New global toggle** on the page (sidebar or header):
  - Label: `Scholar mode`
  - Off (default): show account rewards/analysis only.
  - On: reveal scholar-only controls and tabs.
- **Rename page**: “Rewards Tracker” (from “Scholar Rewards Tracker”).
- **Tabs when Scholar mode is ON**:
  - Summary (always)
  - Tournaments (always)
  - Scholar history (only when Scholar mode is ON)
- **Controls that are scholar-specific** should only render when the toggle is on:
  - Scholar share inputs, payout currency selectors, scholar/owner share tables.
  - Supabase “Scholar history” tab and currency updater controls.
- **Controls that are account-agnostic** stay visible:
  - Username input(s), prices sidebar, rewards/tournament aggregates, per-user totals table, tournaments table.

## Data / Schema Considerations
- Reuse existing data; don’t add columns unless needed.
- Scholar payout display:
  - If `scholar_payout` is present, show it (with token + USD as we do now).
  - Otherwise compute from `scholar_pct` and token prices.
- History filtering for multi-user rows should continue to work; the toggle only affects visibility, not data shape.
- No new DB fields anticipated. Only add if we need a persistent “is_scholar_mode” preference (not required now).

## Implementation Outline
1) **Toggle plumbing**
   - Add a `scholar_mode = st.sidebar.toggle("Scholar mode", value=False)` (or similar).
   - Pass `scholar_mode` into render functions to conditionally show scholar-only sections.

2) **UI adjustments**
   - Rename page title/captions to “Rewards Tracker”.
   - In Summary tab:
     - Always show per-user totals table (account view).
     - Only show scholar share inputs, payout currency selectors, and scholar/owner share tables when `scholar_mode` is True.
   - In Tournaments tab:
     - Keep as-is (account view). No change needed.
   - Scholar history tab:
     - Only render when `scholar_mode` is True.

3) **Code refactor**
   - Split rendering helpers in `pages/20_Rewards_Tracker.py`:
     - `render_account_summary(...)` (always)
     - `render_scholar_controls(...)` (only when scholar_mode)
     - `render_scholar_history(...)` (only when scholar_mode)
   - Ensure no scholar-specific fetches run when `scholar_mode` is False (skip Supabase history fetch, etc.).

4) **Styling/Copy**
   - Update headings/descriptions to reflect “Rewards Tracker”.
   - Scholar-specific labels remain when visible.

## Risks / Edge Cases
- Multi-user history rows: keep current filtering; ensure toggle doesn’t hide necessary error messages.
- Performance: avoid unnecessary Supabase/API calls when scholar mode is off.
- Streamlit layout: toggle likely in sidebar to be discoverable; confirm it doesn’t reset inputs unexpectedly.

## Next Steps
- Add the toggle and pass it through the page.
- Split render functions and guard scholar-only sections.
- Rename page title/caption to “Rewards Tracker”.
- Verify no DB/schema changes are required; keep current Supabase usage intact.
