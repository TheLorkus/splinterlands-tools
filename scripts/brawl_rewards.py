"""Admin-only CLI for managing brawl reward delegations.

This script is intentionally separate from the Streamlit UI so reward delegations are not
publicly editable. It uses the Supabase service role key server-side.

Environment:
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY

Tables (expected):
- brawl_rewards: per-brawl annotation table (brawl_id, player, card_text, foil (optional), note, updated_at, ...)

Commands:
- list-cards
- set --brawl-id ... --player ... --card "..." [--note "..."]
- clear --brawl-id ... --player ...

Notes:
- This script stores the selected card name into brawl_rewards.card_text. It does not
  attempt to manage foil or quantities.
- Upserts are idempotent.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import Any

import requests

BRAWL_REWARDS_TABLE = "brawl_rewards"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _supabase_headers() -> dict[str, str]:
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest_url(path: str) -> str:
    base = _env("SUPABASE_URL").rstrip("/")
    return f"{base}/rest/v1/{path.lstrip('/')}"


def _get(table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    url = _rest_url(table)
    r = requests.get(url, headers=_supabase_headers(), params=params or {}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GET {table} failed: {r.status_code} {r.text}")
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response from {table}: {type(data)}")
    return data  # type: ignore[return-value]


def _upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    url = _rest_url(f"{table}?on_conflict={on_conflict}")
    headers = {**_supabase_headers(), "Prefer": "resolution=merge-duplicates"}
    r = requests.post(url, headers=headers, json=rows, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"UPSERT {table} failed: {r.status_code} {r.text}")


def _normalize_player(player: str) -> str:
    return player.strip()


def _table_supports_foil() -> bool:
    """Best-effort check for whether brawl_rewards has a `foil` column.

    PostgREST errors if we send unknown columns. This check lets the CLI work against
    older schemas that do not have `foil`.
    """

    try:
        _get(BRAWL_REWARDS_TABLE, params={"select": "foil", "limit": "1"})
        return True
    except Exception:
        return False


def _normalize_foil(foil: str | None) -> str | None:
    if foil is None:
        return None
    val = foil.strip().upper()
    if not val:
        return None
    if val not in {"RF", "GF"}:
        raise SystemExit("--foil must be RF or GF")
    return val


def cmd_list_cards(_: argparse.Namespace) -> int:
    print("This CLI does not enforce a preset card list. " 'Use `set --card "..."` with the exact display text you want stored.')
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    brawl_id = str(args.brawl_id).strip()
    guild_id = str(args.guild_id).strip()
    player = _normalize_player(str(args.player))
    if not brawl_id:
        raise SystemExit("--brawl-id is required")
    if not guild_id:
        raise SystemExit("--guild-id is required")
    if not player:
        raise SystemExit("--player is required")

    card_name = str(args.card).strip()
    if not card_name:
        raise SystemExit("--card must be a non-empty string")
    foil = _normalize_foil(str(args.foil) if args.foil is not None else None)
    note = str(args.note).strip() if args.note else None

    payload: dict[str, Any] = {
        "brawl_id": brawl_id,
        "guild_id": guild_id,
        "player": player,
        "card_text": card_name,
        "updated_at": _now_iso(),
    }

    if foil and _table_supports_foil():
        payload["foil"] = foil

    if note:
        payload["note"] = note

    _upsert(BRAWL_REWARDS_TABLE, [payload], on_conflict="brawl_id,player")
    foil_msg = f" foil={foil}" if foil else ""
    print(f"Set brawl reward: brawl_id={brawl_id} player={player} card={card_name}{foil_msg}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    brawl_id = str(args.brawl_id).strip()
    guild_id = str(args.guild_id).strip()
    player = _normalize_player(str(args.player))
    if not brawl_id:
        raise SystemExit("--brawl-id is required")
    if not guild_id:
        raise SystemExit("--guild-id is required")
    if not player:
        raise SystemExit("--player is required")

    payload: dict[str, Any] = {
        "brawl_id": brawl_id,
        "guild_id": guild_id,
        "player": player,
        "card_text": None,
        "note": None,
        "updated_at": _now_iso(),
    }

    if _table_supports_foil():
        payload["foil"] = None

    _upsert(BRAWL_REWARDS_TABLE, [payload], on_conflict="brawl_id,player")
    print(f"Cleared brawl reward: brawl_id={brawl_id} player={player}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brawl_rewards", description="Admin CLI for brawl reward delegations")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-cards", help="Show CLI notes (no preset list)")
    p_list.set_defaults(func=cmd_list_cards)

    p_set = sub.add_parser("set", help="Assign a reward card for a player in a brawl")
    p_set.add_argument("--brawl-id", required=True)
    p_set.add_argument("--guild-id", required=True)
    p_set.add_argument("--player", required=True)
    p_set.add_argument("--card", required=True)
    p_set.add_argument("--foil", required=False, help="Optional foil tag: RF or GF")
    p_set.add_argument("--note", required=False)
    p_set.set_defaults(func=cmd_set)

    p_clear = sub.add_parser("clear", help="Clear a reward card for a player in a brawl")
    p_clear.add_argument("--brawl-id", required=True)
    p_clear.add_argument("--guild-id", required=True)
    p_clear.add_argument("--player", required=True)
    p_clear.set_defaults(func=cmd_clear)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
