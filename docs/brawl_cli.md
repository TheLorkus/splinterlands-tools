<file name=1 path=/Users/allan/Projects/splinter-lands/splinterlands-tools/docs/brawl_cli.md># Brawl CLI Guide

This guide covers the CLI workflow for ingesting brawl history into Supabase.

## Prerequisites

- Python environment with project dependencies installed.
- Supabase credentials available to the process:
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_ANON_KEY` (read-only checks)
- The guild must exist in `public.tracked_guilds` and be `enabled = true`.

## Command

The brawl ingest command is:

```bash
python scripts/ingest_brawls.py --guild-id <guild_id> --last-n <count>
```

Arguments:
- `--guild-id` (required): Guild ID to ingest.
- `--last-n` (optional, default 3): Number of recent cycles to ingest.

## Brawl Reward Delegation (Admin)

Reward card delegations for perfect brawls are intentionally **not editable from the UI**.
They are managed via Supabase or an admin-only CLI.

The admin CLI script lives at:

```
scripts/brawl_rewards.py
```

### Commands

List available reward cards:

```bash
python scripts/brawl_rewards.py list-cards
```

Assign a reward card for a player in a brawl cycle:

```bash
python scripts/brawl_rewards.py set \
  --brawl-id <brawl_id> \
  --player <player_name> \
  --card "<card name>" \
  [--foil RF|GF] \
  [--note "..."]
```

Clear a reward card for a player in a brawl cycle:

```bash
python scripts/brawl_rewards.py clear \
  --brawl-id <brawl_id> \
  --player <player_name>
```

### Behavior and Constraints

- Uses `SUPABASE_SERVICE_ROLE_KEY`; no anon or user auth.
- Upserts into the brawl reward table (one row per brawl/player).
- Intended for guild admins only.
- UI displays rewards read-only once present in Supabase.
- Re-running commands is safe and idempotent.
- If the brawl_rewards table has a foil column, --foil RF|GF will be stored; otherwise the flag is ignored safely.

## Examples

Ingest the last 3 cycles:

```bash
python scripts/ingest_brawls.py --guild-id 9780675dc7e05224af937c37b30c3812d4e2ca30
```

Ingest the last 10 cycles:

```bash
python scripts/ingest_brawls.py --guild-id 9780675dc7e05224af937c37b30c3812d4e2ca30 --last-n 10
```

## What It Does

- Fetches the latest brawl records for the guild from Splinterlands.
- Pulls detail for each brawl ID and upserts into:
  - `public.brawl_cycles`
  - `public.brawl_player_cycle`
- Uses upserts so repeated runs are safe and idempotent.

## Troubleshooting

- "guild is not tracked" warning:
  - Add the guild to `public.tracked_guilds` and set `enabled = true`.
- "Brawl refresh failed" in the UI or CLI errors:
  - Confirm `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set.
  - Verify the Supabase project contains the brawl tables.
- No rows ingested:
  - Check if the guild has recent brawl records in Splinterlands.

## Related

- Brawl dashboard UI: `pages/10_Brawl_Dashboard.py`
- Persistence helpers: `scholar_helper/services/brawl_persistence.py`
- Brawl reward admin CLI: `scripts/brawl_rewards.py`
</file>
