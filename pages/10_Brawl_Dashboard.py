from __future__ import annotations

from typing import Any, cast

import altair as alt
import pandas as pd
import streamlit as st

from core.config import render_footer, setup_page
from features.brawl.service import (
    DEFAULT_GUILD_ID,
    build_history_df_from_cycles,
    build_player_rows,
    build_player_rows_from_supabase,
    compute_player_stats,
    fetch_brawl_cycles_supabase,
    fetch_brawl_player_cycle_supabase,
    fetch_brawl_rewards_supabase,
    fetch_guild_brawls,
    fetch_guild_list,
    fetch_recent_finished_brawl_records,
    get_missing_brawl_ids_in_db,
    ingest_brawl_ids,
    is_guild_tracked,
    search_guilds,
)

setup_page("Brawl Dashboard")
TREND_CYCLE_LIMIT = 20
DEFAULT_BRAWL_CYCLE_COUNT = 20


def render_page() -> None:
    st.title("Brawl Assistant")
    st.caption("Guild brawl history, player detail, and trend analysis.")

    default_guild = st.session_state.get("guild_id_input", DEFAULT_GUILD_ID)
    guild_id_input = st.sidebar.text_input(
        "Guild ID",
        value=default_guild,
        help="Guild to load brawl records for.",
        key="guild_id_input",
    )
    search_query = st.sidebar.text_input(
        "Search guild by name (fuzzy)",
        value="",
        help="Type part of a guild name to search. Select a result to use its ID.",
    )
    selected_match = None
    if search_query.strip():
        matches = search_guilds(search_query, limit=10)
        if matches:
            choice_idx = st.sidebar.selectbox(
                "Select a guild from results",
                options=list(range(len(matches))),
                format_func=lambda i: f"{matches[i].get('name', '').strip()} — {matches[i].get('owner', '')}",
                index=0,
            )
            selected_match = matches[choice_idx]
        else:
            st.sidebar.info("No guilds matched that search.")

    guild_id = selected_match.get("id") if selected_match else guild_id_input or DEFAULT_GUILD_ID

    if not guild_id:
        st.info("Enter a guild ID in the sidebar to load brawl data.")
        return

    cycle_window = st.sidebar.slider(
        "Stored brawl cycles",
        min_value=1,
        max_value=20,
        value=DEFAULT_BRAWL_CYCLE_COUNT,
        step=1,
    )
    tracked = is_guild_tracked(guild_id)
    if not tracked:
        st.sidebar.info("Storage not enabled for this guild.")

    if st.sidebar.button(
        "Refresh last cycles",
        disabled=not tracked,
        help="Fetch and store the most recent brawl cycles in the database.",
    ):
        with st.spinner("Refreshing brawl history in the database..."):
            recent_records = fetch_recent_finished_brawl_records(guild_id, n=cycle_window)
            recent_ids = [str(row.get("tournament_id")) for row in recent_records if row.get("tournament_id")]
            result = ingest_brawl_ids(guild_id, recent_ids, records=recent_records)
        if result.get("cycles") or result.get("players"):
            st.success("Brawl history refreshed.")
            st.rerun()
        else:
            st.error("Brawl refresh failed. Check database credentials or tracked guilds.")

    recent_records = fetch_recent_finished_brawl_records(guild_id, n=cycle_window)
    recent_ids = [str(row.get("tournament_id")) for row in recent_records if row.get("tournament_id")]
    missing_ids = get_missing_brawl_ids_in_db(guild_id, recent_ids)
    using_supabase = bool(recent_ids) and not missing_ids

    if using_supabase:
        with st.spinner("Fetching brawl history from the database..."):
            cycle_rows = fetch_brawl_cycles_supabase(guild_id, recent_ids)
            history = cast(pd.DataFrame, build_history_df_from_cycles(cycle_rows))
            player_rows_raw = fetch_brawl_player_cycle_supabase(guild_id, recent_ids)
            player_rows = cast(pd.DataFrame, build_player_rows_from_supabase(cycle_rows, player_rows_raw))
        st.caption("Source: database")
    else:
        with st.spinner("Fetching brawl history..."):
            history = cast(pd.DataFrame, fetch_guild_brawls(guild_id))
        with st.spinner("Fetching player data for recent brawls..."):
            player_rows = cast(pd.DataFrame, build_player_rows(guild_id, history, max_brawls=40))
        st.caption("Source: Live API")
        if recent_ids:
            missing_count = len(missing_ids)
            st.warning(f"History missing for {missing_count} of {len(recent_ids)} cycles. Click Refresh to store.")

    if history.empty:
        st.warning("No history was returned for this guild.")
        return

    selected_guild_info = None
    try:
        all_guilds = fetch_guild_list()
        selected_guild_info = next((g for g in all_guilds if g.get("id") == guild_id), None)
    except Exception:
        selected_guild_info = None
    selected_name = str((selected_guild_info or {}).get("name") or "").strip()
    guild_label = (selected_name or str(guild_id).strip()).strip()
    guild_url = f"https://next.splinterlands.com/guild/{guild_id}?tab=about"
    st.info(f"Viewing **{guild_label}** · [Open guild page]({guild_url})")

    tabs = st.tabs(["Brawl history", "Player stats", "Guild trends"])

    with tabs[0]:
        st.subheader(f"{guild_label} Brawl History Summary")

        history_columns = [
            col
            for col in [
                "cycle",
                "created_date",
                "tournament_id",
                "brawl_rank",
                "wins",
                "losses",
                "draws",
                "pts",
                "total_merits_payout",
                "total_sps_payout",
                "auto_wins",
            ]
            if col in history.columns
        ]
        history_df = history[history_columns].copy()
        if selected_guild_info:
            info_cols = ["owner", "motto", "level", "brawl_status", "num_members", "rank"]
            info_rows = {col: selected_guild_info.get(col, "") for col in info_cols}
            friendly = {
                "owner": "Owner",
                "motto": "Motto",
                "level": "Level",
                "brawl_status": "Brawl status",
                "num_members": "Members",
                "rank": "Rank",
            }
            info_df = pd.DataFrame([info_rows]).rename(columns=friendly)
            st.markdown("#### Guild info")
            st.dataframe(info_df, hide_index=True, width="stretch")
        rename_map = {
            "cycle": "Cycle",
            "created_date": "Date",
            "tournament_id": "Tournament",
            "brawl_rank": "Rank",
            "wins": "Wins",
            "losses": "Losses",
            "draws": "Draws",
            "pts": "PTS",
            "total_merits_payout": "Merits",
            "total_sps_payout": "SPS",
            "auto_wins": "Auto wins",
        }
        display_history = history_df.rename(columns=rename_map)

        def _style_history(df: pd.DataFrame) -> pd.DataFrame:
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            if "Rank" in df.columns:
                gold = "#f5da68"
                silver = "#d7d9db"
                bronze = "#d29b6f"
                styles.loc[df["Rank"] == 1, "Rank"] = f"background-color: {gold}; color: #3a2a00; font-weight: 800;"
                styles.loc[df["Rank"] == 2, "Rank"] = f"background-color: {silver}; color: #2f2f2f; font-weight: 700;"
                styles.loc[df["Rank"] == 3, "Rank"] = f"background-color: {bronze}; color: #3a1f00; font-weight: 700;"
            return styles

        styled_history = display_history.style.apply(_style_history, axis=None)

        st.dataframe(
            styled_history,
            width="stretch",
            hide_index=True,
            height=400,
        )

        st.markdown("### Drill down into a single brawl")
        cycles = sorted(history_df["cycle"].dropna().unique(), reverse=True)
        if not cycles:
            st.info("Cycle information is required to drill-down into a specific brawl.")
        else:
            selected_cycle = st.selectbox(
                "Select a brawl cycle to see guild member results",
                options=cycles,
                index=0,
            )

            if player_rows.empty:
                st.info("No per player data captured for recent brawls.")
            else:
                brawl_detail_df = player_rows[player_rows["cycle"] == selected_cycle].copy()
                if brawl_detail_df.empty:
                    st.info("No player data found for that specific brawl.")
                else:
                    brawl_id: str | None = None
                    reward_map: dict[str, dict[str, Any]] = {}
                    brawl_ids = brawl_detail_df["tournament_id"].dropna().unique()
                    if len(brawl_ids):
                        brawl_id = str(brawl_ids[0])
                    if using_supabase and brawl_id:
                        reward_rows = fetch_brawl_rewards_supabase(guild_id, brawl_id)
                        for row in reward_rows:
                            player_key = row.get("player")
                            if isinstance(player_key, str) and player_key:
                                reward_map[player_key] = row
                        brawl_detail_df["reward_card"] = brawl_detail_df["player"].map(lambda p: (reward_map.get(p) or {}).get("card_text") or "")
                        brawl_detail_df["reward_foil"] = brawl_detail_df["player"].map(lambda p: (reward_map.get(p) or {}).get("foil") or "")
                    else:
                        brawl_detail_df["reward_card"] = ""
                        brawl_detail_df["reward_foil"] = ""
                    brawl_detail_df["matches"] = brawl_detail_df["wins"] + brawl_detail_df["losses"] + brawl_detail_df["draws"]
                    brawl_detail_df["win_rate"] = (brawl_detail_df["wins"] / brawl_detail_df["matches"].replace(0, 1)).fillna(0.0)
                    brawl_detail_df["win_rate_pct"] = (brawl_detail_df["win_rate"] * 100).round(1)
                    brawl_detail_df = brawl_detail_df.sort_values(
                        ["win_rate", "wins", "losses"],
                        ascending=[False, False, True],
                    )
                    display_cols = [
                        "player",
                        "wins",
                        "losses",
                        "matches",
                        "win_rate_pct",
                        "reward_card",
                    ]
                    display_detail = brawl_detail_df[display_cols].rename(
                        columns={
                            "player": "Player",
                            "wins": "Wins",
                            "losses": "Losses",
                            "matches": "Matches",
                            "win_rate_pct": "Win rate",
                            "reward_card": "Reward card",
                        }
                    )
                    reward_foil = brawl_detail_df["reward_foil"].reindex(display_detail.index)

                    def _win_rate_bg(val) -> str:
                        try:
                            pct = float(val)
                        except Exception:
                            return ""
                        if pct >= 100.0:
                            return "background-color: #f5da68; color: #3a2a00; font-weight: 800;"
                        return ""

                    def _reward_styles(df: pd.DataFrame) -> pd.DataFrame:
                        styles = pd.DataFrame("", index=df.index, columns=df.columns)
                        if "Reward card" not in styles.columns:
                            return styles
                        col_idx = int(styles.columns.get_indexer(pd.Index(["Reward card"]))[0])
                        if col_idx < 0:
                            return styles
                        for idx, foil in reward_foil.items():
                            row_idx = int(styles.index.get_indexer(pd.Index([idx]))[0])
                            if row_idx < 0:
                                continue
                            if foil == "GF":
                                styles.iat[row_idx, col_idx] = "color: #f5da68; font-weight: 700;"
                            elif foil == "RF":
                                styles.iat[row_idx, col_idx] = "color: #b5b5b5; font-weight: 600;"
                        return styles

                    styled_detail = (
                        cast(
                            Any,
                            display_detail.style.format({"Win rate": "{:.1f}%"}),
                        )
                        .map(_win_rate_bg, subset=["Win rate"])
                        .apply(_reward_styles, axis=None)
                    )

                    st.dataframe(
                        styled_detail,
                        width="stretch",
                        hide_index=True,
                        height=400,
                    )
                    if using_supabase:
                        st.info("Reward delegations are read-only in the dashboard. " "To update rewards, use the database console or an admin script.")
                    else:
                        st.info("Refresh brawl history to enable reward display from the database.")

    with tabs[1]:
        st.subheader(f"{guild_label} Player Stats Over Window")

        window_brawls = st.slider(
            "Number of recent brawls to analyze (player stats only)",
            min_value=5,
            max_value=40,
            value=20,
            step=5,
            key="player_window_brawls",
        )

        if player_rows.empty:
            st.info("No per player data captured yet.")
        else:
            stats_df = compute_player_stats(player_rows, window_brawls)
            if stats_df.empty:
                st.info("Not enough data to compute player stats.")
            else:
                display_df = stats_df.copy().sort_values("win_rate", ascending=False)
                display_df["win_rate"] = (display_df["win_rate"] * 100).round(1)
                st.dataframe(
                    display_df[["player", "wins", "losses", "draws", "matches", "win_rate", "brawls_played"]],
                    width="stretch",
                )

    with tabs[2]:
        st.subheader(f"{guild_label} Brawl Trends")
        st.caption(f"Showing the last {TREND_CYCLE_LIMIT} cycles.")

        cycles = sorted(history["cycle"].dropna().unique(), reverse=True)[:TREND_CYCLE_LIMIT]
        if not cycles:
            st.info("Cycle data is required to visualize trends.")
            return

        trend_data = history[history["cycle"].isin(cycles)].copy()
        if trend_data.empty:
            st.info("No guild data available for the selected cycles.")
            return

        trend_columns = ["wins", "losses", "draws"]
        available_counts = [col for col in trend_columns if col in trend_data.columns]
        if not available_counts:
            st.info("No win/loss information available for the selected cycles.")
            return

        agg = trend_data.groupby("cycle")[available_counts].sum().reset_index().sort_values("cycle", ascending=False)
        match_components = [col for col in ["wins", "losses", "draws"] if col in agg.columns]
        agg["matches"] = agg[match_components].sum(axis="columns")
        wins_series = agg.get("wins", pd.Series(0, index=agg.index))
        agg["win_rate"] = wins_series / agg["matches"].replace({0: 1})

        melted = agg.melt(
            id_vars="cycle",
            value_vars=[col for col in ["wins", "losses"] if col in agg.columns],
            var_name="result",
            value_name="count",
        )
        if not melted.empty:
            bar_chart = (
                alt.Chart(melted)
                .mark_bar()
                .encode(
                    x=alt.X("cycle:O", title="Cycle", sort=alt.EncodingSortField(field="cycle", order="descending")),
                    y=alt.Y("count:Q", title="Matches"),
                    color=alt.Color("result:N", title="Result"),
                    tooltip=["cycle", "result", "count"],
                )
                .properties(height=280)
            )
            st.altair_chart(bar_chart, width="stretch")
        else:
            st.info("Not enough data to compute wins vs losses.")

        win_rate_chart = (
            alt.Chart(agg)
            .mark_line(point=True)
            .encode(
                x=alt.X("cycle:O", title="Cycle", sort=alt.EncodingSortField(field="cycle", order="descending")),
                y=alt.Y("win_rate:Q", title="Win rate", axis=alt.Axis(format="%")),
                tooltip=[
                    "cycle",
                    alt.Tooltip("wins", title="Wins"),
                    alt.Tooltip("losses", title="Losses"),
                    alt.Tooltip("win_rate", format=".0%", title="Win rate"),
                ],
            )
            .properties(height=250)
        )
        st.altair_chart(win_rate_chart, width="stretch")


if __name__ == "__main__":
    render_page()
    render_footer()
