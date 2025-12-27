# Tournament Delegations CLI Guide

This guide covers the CLI workflow for managing reward card delegations tied to tournament results.

## Prerequisites

- Python environment with project dependencies installed.
- Database credentials available to the process:
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
- Reward card catalog populated in `public.reward_cards`.

## Commands

The CLI script is:

```bash
python scripts/tournament_delegations.py <command> [options]
```

### list-cards

List enabled reward cards, sorted by sort_order then name.

```bash
python scripts/tournament_delegations.py list-cards
```

### set

Upsert a delegation for a tournament/player by card name.

```bash
python scripts/tournament_delegations.py set \
  --tournament-id <ID> \
  --player <NAME> \
  --card "<Card Name>" \
  --note "optional note"
```

Notes:
- Card name matches are case-insensitive.
- If the card name does not match, the CLI suggests close names.

### clear

Clear a delegation by setting `reward_card_id` to null.

```bash
python scripts/tournament_delegations.py clear \
  --tournament-id <ID> \
  --player <NAME>
```

## Examples

```bash
python scripts/tournament_delegations.py set --tournament-id 12345 --player lorkus --card "Gold Foil Reward" --note "week 3"
python scripts/tournament_delegations.py clear --tournament-id 12345 --player lorkus
python scripts/tournament_delegations.py list-cards
```

## Troubleshooting

- "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY":
  - Export the required environment variables or set them in your shell.
- "Card not found":
  - Ensure the card exists in `reward_cards` and is enabled.
- Delegation not showing in the UI:
  - Verify `tournament_id` and `player` match the tournament results.

## Related

- Storage helpers: `scholar_helper/services/storage.py`
- CLI script: `scripts/tournament_delegations.py`
- Planning doc: `docs/planning_doc.md`
