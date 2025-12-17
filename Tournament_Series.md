# Tournament Series

## Using the Page
- Pick an **Organizer** from the dropdown or choose **(custom)** and type any username; if it isn’t ingested yet, the page will pull tournaments and leaderboards live from the Splinterlands API.
- Optional: choose a **Series config** to load saved include/exclude IDs, date window, **name filter**, and point scheme; otherwise set filters manually (point scheme, name search, start/end date, ruleset filter, include/exclude IDs, limit to N most recent).
- The events table lists date, tournament name, and ruleset; use the **Leaderboard** tab to see series standings with a qualification cutoff line, and the **View leaderboard** dropdown to inspect a single event’s placements/prizes.
- The **Point schemes** tab shows the scoring tables currently available; reach out if a different scoring scheme is needed.
- JSON export at the bottom includes name filter and qualification cutoff so configs can be re-used or stored.

## Point Schemes
- **Balanced:** fixed points 25/18/12/8/5/2 by placement bands; DNP 0.
- **Performance-Focused:** fixed points 50/30/20/15/10/5/1; DNP 0.
- **Participation:** base 1 point with multipliers 3.0/2.5/2.0/1.5/1.2/1.0; DNP 0.

## Saved Configs
- Stored in `series_configs` with fields: name, organizer, point_scheme, include_ids, exclude_ids, include_after, include_before, visibility, name_filter, and qualification_cutoff, plus an optional note.
- Selecting a config applies its point scheme and filters to the page; current UI is read-only for configs (create/update via scripts or direct SQL).
- Use configs to pin “official” series definitions (e.g., sponsor series) while still allowing ad-hoc filters for experimentation.
