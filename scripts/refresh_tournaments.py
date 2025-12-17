"""
Manual tournament ingest runner for a single organizer.

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
    python scripts/refresh_tournaments.py --organizer yggspl-official --max-age-days 600

This mirrors the DB ingest: fetches the organizer's tournaments from the Splinterlands API,
pulls details for each event, and upserts into tournament_events and tournament_results.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests


API_BASE = "https://api.splinterlands.com"


def _get_supabase_creds() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise SystemExit(
            "Missing Supabase credentials. Set SUPABASE_URL and either SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY."
        )
    return url, key


def _http_get(url: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"HTTP GET failed for {url}: {exc}")
        return None


def _normalize_prize_item(item: dict) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    amount = item.get("amount") or item.get("qty") or item.get("value")
    token = item.get("token") or item.get("type")
    text_label = item.get("text")
    usd_value = item.get("usd_value")
    if amount is None and token is None and text_label is None:
        return None
    return {
        "amount": amount,
        "token": token,
        "text": text_label,
        "usd_value": usd_value,
    }


def _parse_prizes(player: dict, payouts: list) -> tuple[Optional[list], Optional[str]]:
    prize_tokens: List[dict] = []
    prize_text_parts: List[str] = []

    direct_prize = (
        player.get("ext_prize_info")
        or player.get("prizes")
        or player.get("prize")
        or player.get("player_prize")
    )
    if isinstance(direct_prize, list):
        for item in direct_prize:
            norm = _normalize_prize_item(item)
            if norm:
                prize_tokens.append(norm)
                text = norm.get("text") or f"{norm.get('amount')} {norm.get('token')}".strip()
                if text:
                    prize_text_parts.append(str(text))
    elif isinstance(direct_prize, dict):
        norm = _normalize_prize_item(direct_prize)
        if norm:
            prize_tokens.append(norm)
            text = norm.get("text") or f"{norm.get('amount')} {norm.get('token')}".strip()
            if text:
                prize_text_parts.append(str(text))
    elif isinstance(direct_prize, str):
        prize_text_parts.append(direct_prize)

    finish = player.get("finish")
    try:
        finish_int = int(finish) if finish is not None else None
    except Exception:
        finish_int = None

    if isinstance(payouts, list) and finish_int is not None:
        for payout in payouts:
            start_place = payout.get("start_place")
            end_place = payout.get("end_place")
            try:
                start_place = int(start_place)
                end_place = int(end_place)
            except Exception:
                continue
            if not (start_place <= finish_int <= end_place):
                continue
            items = payout.get("items") or []
            for item in items:
                norm = _normalize_prize_item(item)
                if norm:
                    prize_tokens.append(norm)
                    text = norm.get("text") or f"{norm.get('amount')} {norm.get('token')}".strip()
                    if text:
                        prize_text_parts.append(str(text))

    if not prize_tokens:
        prize_tokens = None
    prize_text = "; ".join(sorted(set(prize_text_parts))) if prize_text_parts else None
    return prize_tokens, prize_text


def upsert(url: str, key: str, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    resp = requests.post(f"{url}/rest/v1/{table}", json=rows, headers=headers, timeout=30)
    if resp.status_code >= 300:
        raise SystemExit(f"Upsert failed for {table}: {resp.status_code} {resp.text}")


def ingest_organizer(organizer: str, max_age_days: int) -> None:
    supabase_url, supabase_key = _get_supabase_creds()

    list_resp = _http_get(f"{API_BASE}/tournaments/mine", params={"username": organizer})
    if not isinstance(list_resp, list):
        raise SystemExit(f"No tournaments returned for {organizer}")

    cutoff_ts = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    event_rows: list[dict] = []
    result_rows: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in list_resp:
        tid = item.get("id")
        if not tid:
            continue
        detail_resp = _http_get(f"{API_BASE}/tournaments/find", params={"id": tid, "username": organizer}) or {}
        start_date = detail_resp.get("start_date") or item.get("start_date")
        try:
            start_dt = datetime.fromisoformat(str(start_date).replace("Z", "+00:00"))
        except Exception:
            start_dt = None
        if start_dt and start_dt < cutoff_ts:
            continue

        status = detail_resp.get("status") or detail_resp.get("current_round") or item.get("status")
        entrants = (
            detail_resp.get("players_registered")
            or detail_resp.get("num_players")
            or item.get("players_registered")
        )
        payouts = (
            detail_resp.get("data", {}).get("prizes", {}).get("payouts")
            or detail_resp.get("prizes", {}).get("payouts")
            or item.get("data", {}).get("prizes", {}).get("payouts")
            or []
        )
        allowed_cards = detail_resp.get("data", {}).get("allowed_cards") or item.get("data", {}).get("allowed_cards")

        event_rows.append(
            {
                "tournament_id": tid,
                "organizer": organizer,
                "name": item.get("name") or detail_resp.get("name") or tid,
                "start_date": start_dt.isoformat() if start_dt else None,
                "status": status,
                "entrants": entrants,
                "entry_fee_token": None,
                "entry_fee_amount": None,
                "payouts": payouts,
                "allowed_cards": allowed_cards,
                "raw_list": item,
                "raw_detail": detail_resp,
                "updated_at": now_iso,
            }
        )

        players = detail_resp.get("players") or []
        if isinstance(players, list):
            for player in players:
                prize_tokens, prize_text = _parse_prizes(player, payouts)
                result_rows.append(
                    {
                        "tournament_id": tid,
                        "player": player.get("player") or player.get("username"),
                        "finish": player.get("finish"),
                        "prize_tokens": prize_tokens,
                        "prize_text": prize_text,
                        "raw": player,
                        "updated_at": now_iso,
                    }
                )

    if not event_rows:
        print(f"No tournaments within {max_age_days} days for {organizer}")
        return

    upsert(supabase_url, supabase_key, "tournament_events", event_rows)
    upsert(supabase_url, supabase_key, "tournament_results", result_rows)
    print(f"Ingested {len(event_rows)} events and {len(result_rows)} results for {organizer}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tournaments for an organizer.")
    parser.add_argument("--organizer", required=True, help="Organizer username")
    parser.add_argument("--max-age-days", type=int, default=120, help="How many days back to fetch (default 120)")
    args = parser.parse_args()

    ingest_organizer(args.organizer.strip(), args.max_age_days)


if __name__ == "__main__":
    main()
