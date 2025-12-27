from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests

from scholar_helper.services.storage import (
    _postgrest_upsert,
    _supabase_fetch_with_key,
    get_supabase_anon_client,
    get_supabase_service_client,
)

API_BASE = "https://api.splinterlands.com"

TRACKED_GUILDS_TABLE = "tracked_guilds"
BRAWL_CYCLES_TABLE = "brawl_cycles"
BRAWL_PLAYER_CYCLE_TABLE = "brawl_player_cycle"
BRAWL_REWARDS_TABLE = "brawl_rewards"

logger = logging.getLogger(__name__)


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except Exception:
            return None
    return None


def _coerce_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _get_read_client() -> tuple[str, str] | None:
    return get_supabase_anon_client() or get_supabase_service_client()


def _get_write_client() -> tuple[str, str] | None:
    return get_supabase_service_client()


def _fetch_brawl_records(guild_id: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"{API_BASE}/guilds/brawl_records",
        params={"guild_id": guild_id},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    results = data.get("results", []) or []
    return [row for row in results if isinstance(row, dict)]


def _brawl_record_sort_key(record: dict[str, Any]) -> tuple[int, datetime]:
    cycle_val = _coerce_int(record.get("cycle")) or 0
    created = _parse_dt(record.get("created_date")) or datetime.min.replace(tzinfo=UTC)
    return cycle_val, created


def fetch_recent_finished_brawl_records(guild_id: str, n: int = 3) -> list[dict[str, Any]]:
    records = _fetch_brawl_records(guild_id)
    usable = [row for row in records if row.get("tournament_id")]
    usable.sort(key=_brawl_record_sort_key, reverse=True)
    if n and len(usable) > n:
        usable = usable[:n]
    return usable


def fetch_recent_finished_brawl_ids(guild_id: str, n: int = 3) -> list[str]:
    records = fetch_recent_finished_brawl_records(guild_id, n=n)
    return [str(row.get("tournament_id")) for row in records if row.get("tournament_id")]


def is_guild_tracked(guild_id: str) -> bool:
    creds = _get_read_client()
    if creds is None:
        return False
    url, key = creds
    rows = _supabase_fetch_with_key(
        url,
        key,
        TRACKED_GUILDS_TABLE,
        params={
            "guild_id": f"eq.{guild_id}",
            "enabled": "eq.true",
            "limit": 1,
        },
    )
    return bool(rows)


def get_missing_brawl_ids_in_db(guild_id: str, brawl_ids: Sequence[str]) -> list[str]:
    if not brawl_ids:
        return []
    creds = _get_read_client()
    if creds is None:
        return list(brawl_ids)
    url, key = creds
    ids = ",".join(brawl_ids)
    rows = _supabase_fetch_with_key(
        url,
        key,
        BRAWL_CYCLES_TABLE,
        params={
            "guild_id": f"eq.{guild_id}",
            "brawl_id": f"in.({ids})",
            "select": "brawl_id",
        },
    )
    existing = {row.get("brawl_id") for row in rows}
    return [bid for bid in brawl_ids if bid not in existing]


def fetch_brawl_cycles_supabase(guild_id: str, brawl_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not brawl_ids:
        return []
    creds = _get_read_client()
    if creds is None:
        return []
    url, key = creds
    ids = ",".join(brawl_ids)
    return _supabase_fetch_with_key(
        url,
        key,
        BRAWL_CYCLES_TABLE,
        params={
            "guild_id": f"eq.{guild_id}",
            "brawl_id": f"in.({ids})",
            "order": "ends_at.desc.nullslast",
        },
    )


def fetch_brawl_player_cycle_supabase(guild_id: str, brawl_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not brawl_ids:
        return []
    creds = _get_read_client()
    if creds is None:
        return []
    url, key = creds
    ids = ",".join(brawl_ids)
    return _supabase_fetch_with_key(
        url,
        key,
        BRAWL_PLAYER_CYCLE_TABLE,
        params={
            "guild_id": f"eq.{guild_id}",
            "brawl_id": f"in.({ids})",
            "order": "brawl_id.desc",
        },
    )


def fetch_brawl_rewards_supabase(guild_id: str, brawl_id: str) -> list[dict[str, Any]]:
    creds = _get_read_client()
    if creds is None:
        return []
    url, key = creds
    return _supabase_fetch_with_key(
        url,
        key,
        BRAWL_REWARDS_TABLE,
        params={
            "guild_id": f"eq.{guild_id}",
            "brawl_id": f"eq.{brawl_id}",
        },
    )


def build_history_df_from_cycles(cycles: Sequence[dict[str, Any]]) -> pd.DataFrame:
    if not cycles:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for cycle in cycles:
        raw_summary = cycle.get("raw_summary")
        record: dict[str, Any] = {}
        if isinstance(raw_summary, dict):
            candidate = raw_summary.get("record") if isinstance(raw_summary.get("record"), dict) else raw_summary
            if isinstance(candidate, dict):
                record = dict(candidate)
        if not record:
            record = {}
        record.setdefault("tournament_id", cycle.get("brawl_id"))
        if "created_date" not in record and cycle.get("ends_at"):
            record["created_date"] = cycle.get("ends_at")
        rows.append(record)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in [
        "cycle",
        "tournament_id",
        "wins",
        "losses",
        "draws",
        "pts",
        "brawl_rank",
    ]:
        if col not in df.columns:
            df[col] = 0
    if "created_date" in df.columns:
        df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
    if "cycle" in df.columns:
        df = df.sort_values("cycle", ascending=False)
    for col in ["total_merits_payout", "member_merits_payout", "total_sps_payout"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_player_rows_from_supabase(
    cycles: Sequence[dict[str, Any]],
    players: Sequence[dict[str, Any]],
) -> pd.DataFrame:
    if not cycles or not players:
        return pd.DataFrame()
    cycle_map: dict[str, int | None] = {}
    for cycle in cycles:
        brawl_id = cycle.get("brawl_id")
        raw_summary = cycle.get("raw_summary")
        record = None
        if isinstance(raw_summary, dict):
            record = raw_summary.get("record") if isinstance(raw_summary.get("record"), dict) else None
        cycle_val = _coerce_int(record.get("cycle") if isinstance(record, dict) else None)
        if brawl_id:
            cycle_map[str(brawl_id)] = cycle_val

    rows: list[dict[str, Any]] = []
    for player in players:
        brawl_id = player.get("brawl_id")
        name = player.get("player")
        if not brawl_id or not name:
            continue
        wins = _coerce_int(player.get("wins")) or 0
        losses = _coerce_int(player.get("losses")) or 0
        draws = _coerce_int(player.get("draws")) or 0
        rows.append(
            {
                "cycle": cycle_map.get(str(brawl_id)),
                "tournament_id": brawl_id,
                "player": name,
                "wins": wins,
                "losses": losses,
                "draws": draws,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _fetch_brawl_detail(guild_id: str, brawl_id: str) -> dict[str, Any]:
    resp = requests.get(
        f"{API_BASE}/tournaments/find_brawl",
        params={"id": brawl_id, "guild_id": guild_id},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    return payload if isinstance(payload, dict) else {}


def _extract_cycle_fields(record: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    detail_brawl = detail.get("brawl") if isinstance(detail.get("brawl"), dict) else {}
    detail_tournament = detail.get("tournament") if isinstance(detail.get("tournament"), dict) else {}
    return {
        "tier": _coerce_int(record.get("tier") or detail_brawl.get("tier") or detail_tournament.get("tier")),
        "starts_at": _parse_dt(record.get("start_date") or detail_brawl.get("start_date") or detail_tournament.get("start_date")),
        "ends_at": _parse_dt(record.get("end_date") or record.get("created_date") or detail_brawl.get("end_date") or detail_tournament.get("end_date") or detail_brawl.get("created_date")),
        "season_id": _coerce_int(record.get("season_id") or detail_brawl.get("season_id") or detail_tournament.get("season_id")),
    }


def _is_perfect_record(wins: int, losses: int, draws: int) -> bool:
    battles_played = wins + losses + draws
    return battles_played > 0 and wins == battles_played


def ingest_brawl_ids(
    guild_id: str,
    brawl_ids: Sequence[str],
    *,
    records: Sequence[dict[str, Any]] | None = None,
) -> dict[str, int]:
    if not brawl_ids:
        return {"cycles": 0, "players": 0}
    creds = _get_write_client()
    if creds is None:
        return {"cycles": 0, "players": 0}
    url, key = creds
    now_iso = datetime.now(tz=UTC).isoformat()

    records = records or _fetch_brawl_records(guild_id)
    record_by_id = {str(row.get("tournament_id")): row for row in records if row.get("tournament_id")}

    cycle_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    reward_rows: list[dict[str, Any]] = []

    for brawl_id in brawl_ids:
        record = record_by_id.get(brawl_id, {})
        try:
            detail = _fetch_brawl_detail(guild_id, brawl_id)
        except Exception as exc:
            logger.warning("Failed to fetch brawl detail for %s: %s", brawl_id, exc)
            continue

        cycle_fields = _extract_cycle_fields(record, detail)
        cycle_rows.append(
            {
                "brawl_id": brawl_id,
                "guild_id": guild_id,
                "tier": cycle_fields.get("tier"),
                "starts_at": cycle_fields.get("starts_at").isoformat() if cycle_fields.get("starts_at") else None,
                "ends_at": cycle_fields.get("ends_at").isoformat() if cycle_fields.get("ends_at") else None,
                "season_id": cycle_fields.get("season_id"),
                "raw_summary": {"record": record, "detail": detail},
                "ingested_at": now_iso,
            }
        )

        players = detail.get("players", [])
        if not isinstance(players, list):
            players = []
        for player in players:
            if not isinstance(player, dict):
                continue
            name = player.get("player") or player.get("name")
            if not name:
                continue
            record_payload = player.get("record") if isinstance(player.get("record"), dict) else player
            wins = _coerce_int(record_payload.get("wins")) or 0
            losses = _coerce_int(record_payload.get("losses")) or 0
            draws = _coerce_int(record_payload.get("draws")) or 0
            battles_played = wins + losses + draws
            player_rows.append(
                {
                    "brawl_id": brawl_id,
                    "guild_id": guild_id,
                    "player": str(name),
                    "frays_entered": _coerce_int(record_payload.get("frays_entered") or record_payload.get("frays")),
                    "battles_played": battles_played,
                    "wins": wins,
                    "losses": losses,
                    "draws": draws,
                    "submitted": record_payload.get("submitted"),
                    "raw": player,
                    "updated_at": now_iso,
                }
            )
            if _is_perfect_record(wins, losses, draws):
                reward_rows.append(
                    {
                        "brawl_id": brawl_id,
                        "guild_id": guild_id,
                        "player": str(name),
                        "is_perfect": True,
                        "updated_at": now_iso,
                    }
                )

    if cycle_rows:
        _postgrest_upsert(url, key, BRAWL_CYCLES_TABLE, cycle_rows, on_conflict="brawl_id")
    if player_rows:
        _postgrest_upsert(url, key, BRAWL_PLAYER_CYCLE_TABLE, player_rows, on_conflict="brawl_id,player")
    if reward_rows:
        _postgrest_upsert(url, key, BRAWL_REWARDS_TABLE, reward_rows, on_conflict="brawl_id,player")

    return {"cycles": len(cycle_rows), "players": len(player_rows)}


def upsert_brawl_rewards(rows: Iterable[dict[str, Any]]) -> bool:
    rows = list(rows)
    if not rows:
        return False
    creds = _get_write_client()
    if creds is None:
        return False
    url, key = creds
    return _postgrest_upsert(url, key, BRAWL_REWARDS_TABLE, rows, on_conflict="brawl_id,player")
