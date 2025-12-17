from __future__ import annotations

import os
import logging
from typing import Dict, Iterable, Optional, Sequence
from datetime import datetime, timezone

from dotenv import load_dotenv
import requests
try:
    import streamlit as st
except Exception:  # Streamlit not available in pure CLI runs (e.g., tests)
    st = None

from scholar_helper.models import AggregatedTotals, SeasonWindow, TournamentResult

SEASON_TABLE = "season_rewards"
TOURNAMENT_TABLE = "tournament_logs"
TOURNAMENT_EVENTS_TABLE = "tournament_events"
TOURNAMENT_RESULTS_TABLE = "tournament_results"
TOURNAMENT_ORGANIZERS_TABLE = "tournament_ingest_organizers"
SERIES_CONFIGS_TABLE = "series_configs"

logger = logging.getLogger(__name__)

_last_error: Optional[str] = None

load_dotenv()


def _get_supabase_credentials() -> Optional[tuple[str, str]]:
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


def get_supabase_client() -> Optional[tuple[str, str]]:
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


def get_last_supabase_error() -> Optional[str]:
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


def _build_auth_headers(key: str, content_type: str | None = None) -> Dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _supabase_fetch(path: str, params: Dict[str, object] | None = None) -> list[Dict[str, object]]:
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


def refresh_tournament_ingest_all(max_age_days: int = 3) -> bool:
    """
    Trigger the ingest function for all active organizers with a limited window.
    Returns True on success, False on failure or missing creds.
    """
    creds = get_supabase_client()
    if creds is None:
        return False
    url, key = creds
    payload = {"max_age_days": max_age_days}
    try:
        resp = requests.post(
            f"{url}/rest/v1/rpc/refresh_tournament_ingest",
            headers=_build_auth_headers(key, "application/json"),
            json=payload,
            timeout=60,
        )
    except Exception as exc:
        global _last_error
        _last_error = f"Ingest trigger failed: {exc}"
        logger.error(_last_error)
        return False
    if resp.status_code >= 300:
        _last_error = f"Ingest trigger failed: {resp.status_code} {resp.text[:512]}"
        logger.error(_last_error)
        return False
    return True


def _to_iso(dt: datetime | str | None) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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


def upsert_tournament_events(events: Sequence[Dict[str, object]]) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    if not events:
        return

    url, key = creds
    _postgrest_upsert(url, key, TOURNAMENT_EVENTS_TABLE, events)


def upsert_tournament_results(results: Sequence[Dict[str, object]]) -> None:
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
) -> list[Dict[str, object]]:
    """
    Fetch stored tournament events (ingested metadata) ordered newest-first.
    """
    params: Dict[str, object] = {"order": "start_date.desc"}
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
) -> list[Dict[str, object]]:
    """
    Fetch leaderboard rows (with points) from the tournament_result_points view.
    Supports filtering by organizer, date window, or multiple tournament ids.
    """
    params: Dict[str, object] = {"order": "finish.asc.nullslast"}
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
    params: Dict[str, object] = {
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


def fetch_series_configs(organizer: str | None = None) -> list[Dict[str, object]]:
    """
    Fetch saved series configs (public).
    """
    params: Dict[str, object] = {"order": "name.asc"}
    if organizer:
        params["organizer"] = f"eq.{organizer}"
    return _supabase_fetch(SERIES_CONFIGS_TABLE, params)


def fetch_point_schemes() -> list[Dict[str, object]]:
    """
    Fetch available point schemes (public).
    """
    params: Dict[str, object] = {"order": "slug.asc"}
    return _supabase_fetch("point_schemes", params)


def fetch_tournament_leaderboard_totals_supabase(
    organizer: str, scheme: str = "balanced"
) -> list[Dict[str, object]]:
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


def fetch_season_history(username: str) -> list[Dict[str, object]]:
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
