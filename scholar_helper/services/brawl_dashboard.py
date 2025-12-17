"""Helper utilities ported from the Splinterlands Brawl Dashboard."""

from __future__ import annotations

import requests
import pandas as pd
import streamlit as st
from difflib import SequenceMatcher

API_BASE = "https://api.splinterlands.com"
DEFAULT_GUILD_ID = "9780675dc7e05224af937c37b30c3812d4e2ca30"


@st.cache_data(ttl=300)
def fetch_guild_brawls(guild_id: str) -> pd.DataFrame:
    resp = requests.get(f"{API_BASE}/guilds/brawl_records", params={"guild_id": guild_id}, timeout=15)
    resp.raise_for_status()
    data = resp.json() or {}
    results = data.get("results", []) or []
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
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


@st.cache_data(ttl=300)
def fetch_brawl_details(tournament_id: str, guild_id: str) -> dict:
    resp = requests.get(
        f"{API_BASE}/tournaments/find_brawl",
        params={"id": tournament_id, "guild_id": guild_id},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() or {}


def build_player_rows(guild_id: str, history: pd.DataFrame, max_brawls: int = 40) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    cycles = sorted(history["cycle"].dropna().unique(), reverse=True)[:max_brawls]
    rows = []
    for _, row in history[history["cycle"].isin(cycles)].iterrows():
        tournament_id = row["tournament_id"]
        cycle = int(row["cycle"]) if not pd.isna(row["cycle"]) else None
        try:
            details = fetch_brawl_details(tournament_id, guild_id)
        except Exception:
            continue
        players = details.get("players", [])
        if not players:
            continue
        for player in players:
            name = player.get("player") or player.get("name")
            if not name:
                continue
            record = player.get("record") or player
            rows.append(
                {
                    "cycle": cycle,
                    "tournament_id": tournament_id,
                    "player": name,
                    "wins": int(record.get("wins", 0)),
                    "losses": int(record.get("losses", 0)),
                    "draws": int(record.get("draws", 0)),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def compute_player_stats(players_df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    if players_df.empty:
        return pd.DataFrame()
    cycles = sorted(players_df["cycle"].dropna().unique(), reverse=True)
    window_cycles = cycles[:window]
    window_rows = players_df[players_df["cycle"].isin(window_cycles)]
    if window_rows.empty:
        return pd.DataFrame()
    agg = (
        window_rows.groupby("player")
        .agg(
            wins=("wins", "sum"),
            losses=("losses", "sum"),
            draws=("draws", "sum"),
            matches=("wins", "sum"),
        )
        .reset_index()
    )
    agg["matches"] = agg["wins"] + agg["losses"] + agg["draws"]
    agg["win_rate"] = agg["wins"] / agg["matches"].replace(0, 1)
    agg["brawls_played"] = window_rows.groupby("player")["tournament_id"].nunique().values
    return agg


@st.cache_data(ttl=86400)
def fetch_guild_list() -> list[dict]:
    resp = requests.get(f"{API_BASE}/guilds/list", timeout=20)
    resp.raise_for_status()
    data = resp.json() or {}
    guilds = data.get("guilds") or []
    if not isinstance(guilds, list):
        return []
    return guilds


def search_guilds(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    guilds = fetch_guild_list()
    if not guilds:
        return []
    q = query.strip().lower()
    scored: list[tuple[float, dict]] = []
    for g in guilds:
        name = str(g.get("name") or "").strip().lower()
        if not name:
            continue
        score = SequenceMatcher(None, q, name).ratio()
        if q in name:
            score += 0.2
        scored.append((score, g))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = []
    for score, g in scored[:limit]:
        g_copy = dict(g)
        g_copy["_match_score"] = score
        top.append(g_copy)
    return top
