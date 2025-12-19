from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scholar_helper.services.storage import (  # noqa: E402
    REWARD_CARDS_TABLE,
    TOURNAMENT_REWARDS_TABLE,
    _postgrest_upsert,
    _supabase_fetch_with_key,
    get_supabase_service_client,
)


def _exit_with_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _get_service_creds() -> tuple[str, str] | None:
    return get_supabase_service_client()


def _fetch_reward_cards(url: str, key: str, enabled_only: bool = True) -> list[dict[str, object]]:
    params: dict[str, object] = {"order": "sort_order.asc.nullslast,name.asc"}
    if enabled_only:
        params["enabled"] = "eq.true"
    return _supabase_fetch_with_key(url, key, REWARD_CARDS_TABLE, params)


def _resolve_reward_card_id(url: str, key: str, card_name: str) -> str | None:
    if not card_name:
        return None
    cards = _fetch_reward_cards(url, key, enabled_only=True)
    name_lookup = {str(card.get("name") or ""): card for card in cards}
    if card_name in name_lookup:
        return str(name_lookup[card_name].get("reward_card_id"))
    lower_lookup = {name.lower(): card for name, card in name_lookup.items() if name}
    match = lower_lookup.get(card_name.lower())
    if match:
        return str(match.get("reward_card_id"))
    return None


def list_cards(args: argparse.Namespace) -> int:
    creds = _get_service_creds()
    if creds is None:
        return _exit_with_error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
    url, key = creds
    cards = _fetch_reward_cards(url, key, enabled_only=True)
    if not cards:
        print("No enabled reward cards found.")
        return 0
    for card in cards:
        name = str(card.get("name") or "")
        sort_order = card.get("sort_order")
        notes = card.get("notes")
        suffix = []
        if sort_order is not None:
            suffix.append(f"order={sort_order}")
        if notes:
            suffix.append(f"notes={notes}")
        extra = f" ({', '.join(suffix)})" if suffix else ""
        print(f"- {name}{extra}")
    return 0


def set_delegation(args: argparse.Namespace) -> int:
    creds = _get_service_creds()
    if creds is None:
        return _exit_with_error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
    url, key = creds
    card_id = _resolve_reward_card_id(url, key, args.card)
    if not card_id:
        cards = _fetch_reward_cards(url, key, enabled_only=True)
        names = [str(card.get("name") or "") for card in cards if card.get("name")]
        suggestions = get_close_matches(args.card, names, n=5)
        message = f"Card not found: {args.card}"
        if suggestions:
            message += f". Did you mean: {', '.join(suggestions)}?"
        return _exit_with_error(message)
    payload = [
        {
            "tournament_id": args.tournament_id,
            "player": args.player,
            "reward_card_id": card_id,
            "note": args.note,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    ]
    if not _postgrest_upsert(url, key, TOURNAMENT_REWARDS_TABLE, payload, on_conflict="tournament_id,player"):
        return _exit_with_error("Failed to upsert tournament reward.")
    print("Delegation saved.")
    return 0


def clear_delegation(args: argparse.Namespace) -> int:
    creds = _get_service_creds()
    if creds is None:
        return _exit_with_error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
    url, key = creds
    payload = [
        {
            "tournament_id": args.tournament_id,
            "player": args.player,
            "reward_card_id": None,
            "note": None,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    ]
    if not _postgrest_upsert(url, key, TOURNAMENT_REWARDS_TABLE, payload, on_conflict="tournament_id,player"):
        return _exit_with_error("Failed to clear tournament reward.")
    print("Delegation cleared.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage tournament reward card delegations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-cards", help="List enabled reward cards.")
    list_parser.set_defaults(func=list_cards)

    set_parser = subparsers.add_parser("set", help="Set a tournament reward card delegation.")
    set_parser.add_argument("--tournament-id", required=True)
    set_parser.add_argument("--player", required=True)
    set_parser.add_argument("--card", required=True)
    set_parser.add_argument("--note")
    set_parser.set_defaults(func=set_delegation)

    clear_parser = subparsers.add_parser("clear", help="Clear a tournament reward card delegation.")
    clear_parser.add_argument("--tournament-id", required=True)
    clear_parser.add_argument("--player", required=True)
    clear_parser.set_defaults(func=clear_delegation)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
