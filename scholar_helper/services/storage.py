from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import requests
from dotenv import load_dotenv

try:
    import streamlit as st
except Exception:  # Streamlit not available in pure CLI runs (e.g., tests)
    st = None

if TYPE_CHECKING:
    from scholar_helper.models import AggregatedTotals, SeasonWindow, TournamentResult

SEASON_TABLE = "season_rewards"
TOURNAMENT_TABLE = "tournament_logs"
TOURNAMENT_EVENTS_TABLE = "tournament_events"
TOURNAMENT_RESULTS_TABLE = "tournament_results"
TOURNAMENT_ORGANIZERS_TABLE = "tournament_ingest_organizers"
SERIES_CONFIGS_TABLE = "series_configs"
TOURNAMENT_INGEST_STATE_TABLE = "tournament_ingest_state"

API_BASE = "https://api.splinterlands.com"
DEFAULT_MAX_TOURNAMENTS = 200
FETCH_TIMEOUT_SECONDS = 20

logger = logging.getLogger(__name__)

_last_error: str | None = None

load_dotenv()


def _get_supabase_credentials() -> tuple[str, str] | None:
    """Return (url, key) using env first, then Streamlit secrets."""
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if (not url or not key) and st is not None:
        secrets = st.secrets
        url = url or secrets.get("SUPABASE_URL")
        key = (
            key
            or secrets.get("SUPABASE_SERVICE_ROLE_KEY")
            or secrets.get("SUPABASE_SERVICE_KEY")
            or secrets.get("SUPABASE_ANON_KEY")
        )
    if not url or not key:
        return None
    return url, key


def get_supabase_client() -> tuple[str, str] | None:
    """
    Backwards-compatible helper used by the app code to check whether Supabase is configured.

    We return credentials instead of a Supabase client to avoid dependency conflicts on Streamlit
    Cloud. The upsert helpers below use the REST API directly via requests.
    """
    global _last_error
    creds = _get_supabase_credentials()
    if not creds:
        _last_error = "Missing SUPABASE_URL or key"
        return None
    _last_error = None
    return creds


def get_last_supabase_error() -> str | None:
    return _last_error


def _postgrest_upsert(url: str, key: str, table: str, rows) -> None:
    global _last_error
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    resp = requests.post(f"{url}/rest/v1/{table}", json=rows, headers=headers, timeout=15)
    if resp.status_code >= 300:
        _last_error = f"Supabase upsert failed: {resp.status_code} {resp.text}"


def _build_auth_headers(key: str, content_type: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _supabase_fetch(path: str, params: dict[str, object] | None = None) -> list[dict[str, object]]:
    """Lightweight GET helper for Supabase REST endpoints/views."""
    global _last_error
    creds = get_supabase_client()
    if creds is None:
        return []

    url, key = creds
    try:
        resp = requests.get(
            f"{url}/rest/v1/{path}",
            headers=_build_auth_headers(key),
            params=params or {},
            timeout=20,
        )
    except Exception as exc:
        _last_error = f"Supabase fetch failed: {exc}"
        logger.error(_last_error)
        return []

    if resp.status_code >= 300:
        _last_error = f"Supabase fetch failed: {resp.status_code} {resp.text[:512]}"
        logger.error(_last_error)
        return []

    data = resp.json() or []
    if not isinstance(data, list):
        return []
    return data


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _http_get_json(url: str, params: dict[str, object] | None = None) -> object | None:
    try:
        resp = requests.get(url, params=params, timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("HTTP GET failed for %s: %s", url, exc)
        return None


def _normalize_prize_item(item: object) -> dict[str, object] | None:
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


def _parse_prizes(player: dict[str, object], payouts: list) -> tuple[list | None, str | None]:
    prize_tokens: list[dict[str, object]] = []
    prize_text_parts: list[str] = []

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
            if not isinstance(payout, dict):
                continue
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

    prize_text = "; ".join(sorted(set(prize_text_parts))) if prize_text_parts else None
    return (prize_tokens or None), prize_text


def _upsert_ingest_state(rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        return
    creds = get_supabase_client()
    if creds is None:
        return
    url, key = creds
    try:
        _postgrest_upsert(url, key, TOURNAMENT_INGEST_STATE_TABLE, rows)
    except Exception as exc:
        logger.error("Ingest state upsert failed: %s", exc)


def _ingest_organizer_tournaments(
    organizer: str,
    max_age_days: int,
    max_tournaments: int,
) -> tuple[int, int]:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    cutoff_ts = now - timedelta(days=max_age_days)

    list_resp = _http_get_json(f"{API_BASE}/tournaments/mine", params={"username": organizer})
    if not isinstance(list_resp, list):
        raise RuntimeError(f"No tournaments returned for organizer {organizer}")

    event_rows: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    processed = 0

    for item in list_resp:
        if processed >= max_tournaments:
            break
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        if not tid:
            continue

        list_start = _parse_datetime(item.get("start_date"))
        if list_start and list_start < cutoff_ts:
            continue

        detail_resp = _http_get_json(
            f"{API_BASE}/tournaments/find",
            params={"id": tid, "username": organizer},
        )
        if not isinstance(detail_resp, dict):
            continue

        start_date = _parse_datetime(detail_resp.get("start_date") or item.get("start_date"))
        if start_date and start_date < cutoff_ts:
            continue

        status = detail_resp.get("status") or detail_resp.get("current_round") or item.get("status")
        entrants = (
            detail_resp.get("players_registered")
            or detail_resp.get("num_players")
            or item.get("players_registered")
        )
        detail_data = detail_resp.get("data") if isinstance(detail_resp.get("data"), dict) else {}
        item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        payouts = (
            detail_data.get("prizes", {}).get("payouts")
            or detail_resp.get("prizes", {}).get("payouts")
            or item_data.get("prizes", {}).get("payouts")
            or []
        )
        allowed_cards = detail_data.get("allowed_cards") or item_data.get("allowed_cards")

        event_rows.append(
            {
                "tournament_id": str(tid),
                "organizer": organizer,
                "name": item.get("name") or detail_resp.get("name") or str(tid),
                "start_date": start_date.isoformat() if start_date else None,
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
                if not isinstance(player, dict):
                    continue
                prize_tokens, prize_text = _parse_prizes(player, payouts)
                result_rows.append(
                    {
                        "tournament_id": str(tid),
                        "player": player.get("player") or player.get("username"),
                        "finish": player.get("finish"),
                        "prize_tokens": prize_tokens,
                        "prize_text": prize_text,
                        "raw": player,
                        "updated_at": now_iso,
                    }
                )

        processed += 1

    if event_rows:
        upsert_tournament_events(event_rows)
    if result_rows:
        upsert_tournament_results(result_rows)

    return len(event_rows), len(result_rows)


def _fallback_organizers() -> list[str]:
    if st is None:
        return []
    raw = st.secrets.get("DEFAULT_USERNAMES")
    if isinstance(raw, str):
        candidates = [item.strip() for item in raw.replace("\n", ",").split(",")]
    elif isinstance(raw, list):
        candidates = [str(item).strip() for item in raw]
    else:
        return []
    return [name for name in candidates if name]


def refresh_tournament_ingest_all(max_age_days: int = 3) -> bool:
    """
    Fetch recent tournaments and upsert directly via PostgREST (no edge functions).
    Returns True on success, False on failure or missing creds.
    """
    global _last_error
    creds = get_supabase_client()
    if creds is None:
        return False

    organizers = fetch_tournament_ingest_organizers(active_only=True)
    if not organizers:
        organizers = _fallback_organizers()
    if not organizers:
        _last_error = "No active organizers found for ingest."
        return False

    try:
        max_tournaments = int(os.getenv("TOURNAMENT_INGEST_MAX_TOURNAMENTS", DEFAULT_MAX_TOURNAMENTS))
    except Exception:
        max_tournaments = DEFAULT_MAX_TOURNAMENTS

    failures: list[str] = []
    now_iso = datetime.now(UTC).isoformat()
    for organizer in organizers:
        _upsert_ingest_state(
            [
                {
                    "organizer": organizer,
                    "last_run_at": now_iso,
                    "last_window_days": max_age_days,
                    "updated_at": now_iso,
                }
            ]
        )
        try:
            event_count, result_count = _ingest_organizer_tournaments(
                organizer,
                max_age_days=max_age_days,
                max_tournaments=max_tournaments,
            )
            _upsert_ingest_state(
                [
                    {
                        "organizer": organizer,
                        "last_success_at": now_iso,
                        "last_error": None,
                        "last_event_count": event_count,
                        "last_result_count": result_count,
                        "last_window_days": max_age_days,
                        "updated_at": now_iso,
                    }
                ]
            )
        except Exception as exc:
            message = str(exc)
            failures.append(f"{organizer}: {message}")
            _upsert_ingest_state(
                [
                    {
                        "organizer": organizer,
                        "last_error": message,
                        "last_window_days": max_age_days,
                        "updated_at": now_iso,
                    }
                ]
            )

    if failures:
        _last_error = "Ingest failed for: " + "; ".join(failures)
        logger.error(_last_error)
        return False
    _last_error = None
    return True


def _to_iso(dt: datetime | str | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def upsert_season_totals(
    season: SeasonWindow,
    username: str,
    totals: AggregatedTotals,
    scholar_pct: float,
    payout_currency: str,
    table: str = SEASON_TABLE,
) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    payload = {
        "season_id": season.id,
        "season_start": season.starts.isoformat(),
        "season_end": season.ends.isoformat(),
        "username": username,
        "ranked_tokens": totals.ranked.token_amounts,
        "brawl_tokens": totals.brawl.token_amounts,
        "tournament_tokens": totals.tournament.token_amounts,
        "entry_fees_tokens": totals.entry_fees.token_amounts,
        "ranked_usd": totals.ranked.usd,
        "brawl_usd": totals.brawl.usd,
        "tournament_usd": totals.tournament.usd,
        "entry_fees_usd": totals.entry_fees.usd,
        "overall_usd": totals.overall.usd,
        "scholar_pct": scholar_pct,
        "payout_currency": payout_currency,
    }
    url, key = creds
    _postgrest_upsert(url, key, table, payload)


def upsert_tournament_logs(
    tournaments: Iterable[TournamentResult], username: str, table: str = TOURNAMENT_TABLE
) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    rows = []
    for t in tournaments:
        rows.append(
            {
                "username": username,
                "tournament_id": t.id,
                "name": t.name,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "finish": t.finish,
                "entry_fee_token": t.entry_fee.token if t.entry_fee else None,
                "entry_fee_amount": t.entry_fee.amount if t.entry_fee else None,
                "rewards": [r.__dict__ for r in t.rewards],
                "raw": t.raw,
            }
        )
    if rows:
        url, key = creds
        _postgrest_upsert(url, key, table, rows)


def upsert_tournament_events(events: Sequence[dict[str, object]]) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    if not events:
        return

    url, key = creds
    _postgrest_upsert(url, key, TOURNAMENT_EVENTS_TABLE, events)


def upsert_tournament_results(results: Sequence[dict[str, object]]) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    if not results:
        return

    url, key = creds
    _postgrest_upsert(url, key, TOURNAMENT_RESULTS_TABLE, results)


def fetch_tournament_events_supabase(
    organizer: str | None = None,
    limit: int = 200,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> list[dict[str, object]]:
    """
    Fetch stored tournament events (ingested metadata) ordered newest-first.
    """
    params: dict[str, object] = {"order": "start_date.desc"}
    if organizer:
        params["organizer"] = f"eq.{organizer}"
    start_after = _to_iso(since)
    start_before = _to_iso(until)
    filters = []
    if start_after:
        filters.append(f"start_date.gte.{start_after}")
    if start_before:
        filters.append(f"start_date.lte.{start_before}")
    if filters:
        params["and"] = f"({','.join(filters)})"
    if limit:
        params["limit"] = limit
    return _supabase_fetch("tournament_events", params)


def fetch_tournament_results_supabase(
    tournament_id: str | None = None,
    tournament_ids: Sequence[str] | None = None,
    organizer: str | None = None,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
) -> list[dict[str, object]]:
    """
    Fetch leaderboard rows (with points) from the tournament_result_points view.
    Supports filtering by organizer, date window, or multiple tournament ids.
    """
    params: dict[str, object] = {"order": "finish.asc.nullslast"}
    if tournament_id:
        params["tournament_id"] = f"eq.{tournament_id}"
    elif tournament_ids:
        ids = [tid for tid in tournament_ids if tid]
        if ids:
            params["tournament_id"] = f"in.({','.join(ids)})"
    if organizer:
        params["organizer"] = f"eq.{organizer}"
    start_after = _to_iso(since)
    start_before = _to_iso(until)
    filters = []
    if start_after:
        filters.append(f"start_date.gte.{start_after}")
    if start_before:
        filters.append(f"start_date.lte.{start_before}")
    if filters:
        params["and"] = f"({','.join(filters)})"
    return _supabase_fetch("tournament_result_points", params)


def fetch_tournament_ingest_organizers(active_only: bool = True) -> list[str]:
    """
    Return known organizers from the ingest table (for UI dropdowns).
    """
    params: dict[str, object] = {
        "select": "username,active",
        "order": "username.asc",
    }
    if active_only:
        params["active"] = "eq.true"
    rows = _supabase_fetch(TOURNAMENT_ORGANIZERS_TABLE, params)
    usernames: list[str] = []
    for row in rows:
        name = row.get("username")
        if isinstance(name, str) and name.strip():
            usernames.append(name.strip())
    return usernames


def fetch_series_configs(organizer: str | None = None) -> list[dict[str, object]]:
    """
    Fetch saved series configs (public).
    """
    params: dict[str, object] = {"order": "name.asc"}
    if organizer:
        params["organizer"] = f"eq.{organizer}"
    return _supabase_fetch(SERIES_CONFIGS_TABLE, params)


def fetch_point_schemes() -> list[dict[str, object]]:
    """
    Fetch available point schemes (public).
    """
    params: dict[str, object] = {"order": "slug.asc"}
    return _supabase_fetch("point_schemes", params)


def fetch_tournament_leaderboard_totals_supabase(
    organizer: str, scheme: str = "balanced"
) -> list[dict[str, object]]:
    """
    Aggregated series leaderboard per organizer using the points views.
    """
    if not organizer:
        return []

    points_column = {
        "balanced": "points_balanced",
        "performance": "points_performance",
        "participation": "points_participation",
    }.get(scheme, "points_balanced")

    params = {
        "organizer": f"eq.{organizer}",
        "order": f"{points_column}.desc.nullslast",
    }
    return _supabase_fetch("tournament_leaderboard_totals", params)


def fetch_season_history(username: str) -> list[dict[str, object]]:
    creds = get_supabase_client()
    if creds is None:
        return []

    url, key = creds
    endpoint = (
        f"{url}/rest/v1/{SEASON_TABLE}?username=eq.{username}&order=season_id.desc"
    )
    logger.debug("Fetching season history: %s headers=apikey", endpoint)
    headers = _build_auth_headers(key)
    resp = requests.get(endpoint, headers=headers, timeout=15)
    if resp.status_code >= 300:
        global _last_error
        _last_error = (
            f"Supabase fetch failed: {resp.status_code} {resp.text[:2048]}"
        )
        logger.error("Supabase fetch failed: %s %s", resp.status_code, resp.text)
        return []
    data = resp.json() or []
    logger.debug("Fetched %d history rows for %s", len(data), username)
    if not isinstance(data, list):
        return []
    return data


def update_season_currency(username: str, season_id: int, currency: str) -> bool:
    creds = get_supabase_client()
    if creds is None:
        return False

    url, key = creds
    headers = _build_auth_headers(key, content_type="application/json")
    resp = requests.patch(
        f"{url}/rest/v1/{SEASON_TABLE}?username=eq.{username}&season_id=eq.{season_id}",
        json={"payout_currency": currency},
        headers=headers,
        timeout=15,
    )
    if resp.status_code >= 300:
        global _last_error
        _last_error = f"Supabase update failed: {resp.status_code} {resp.text}"
        return False
    return True
