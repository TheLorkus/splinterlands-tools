from __future__ import annotations

from datetime import datetime, date
import pandas as pd
import streamlit as st

from core.config import setup_page
from scholar_helper.services.storage import (
    fetch_series_configs,
    fetch_tournament_events_supabase,
    fetch_tournament_results_supabase,
    get_last_supabase_error,
)


def setup_if_standalone() -> None:
    try:
        import streamlit as st  # type: ignore

        if not st.session_state.get("__series_setup_done"):
            setup_page("Tournament Series")
            st.session_state["__series_setup_done"] = True
    except Exception:
        pass


def _parse_date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _format_date(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d")


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _table_height_for_rows(
    row_count: int,
    *,
    row_height: int = 32,
    min_height: int = 260,
    max_height: int = 1100,
    extra: int = 160,
) -> int:
    count = max(1, row_count)
    return min(max_height, max(min_height, count * row_height + extra))


def render_page(embed_mode: bool = False) -> None:
    if not embed_mode:
        setup_if_standalone()
        st.title("Tournament Series")
        st.caption("Pick an organizer and config to view its saved series leaderboard.")

    params = st.query_params
    default_org = params.get("organizer") or params.get("org") or "lorkus"
    default_config = params.get("config") or params.get("name") or params.get("id") or "Delegated & Dangerous"

    organizer = st.text_input("Organizer", value=default_org, placeholder="e.g., lorkus or clove71").strip()
    if not organizer:
        st.info("Enter an organizer to load their saved series configs.")
        return

    configs = fetch_series_configs(organizer)
    if not configs:
        supabase_error = get_last_supabase_error()
        if supabase_error:
            st.error(f"Database query failed: {supabase_error}")
        else:
            st.info("No saved configs found for this organizer.")
        return

    config_labels = [c.get("name") or str(c.get("id")) for c in configs]
    default_idx = 0
    if default_config:
        for idx, cfg in enumerate(configs):
            if default_config in (cfg.get("name"), str(cfg.get("id"))):
                default_idx = idx
                break
    selected_label = st.selectbox("Config", options=config_labels, index=default_idx)
    selected_config = next((c for c in configs if (c.get("name") or str(c.get("id"))) == selected_label), None)
    if not selected_config:
        st.warning("Select a config to continue.")
        return

    # Extract filters from config
    include_ids = selected_config.get("include_ids") or []
    exclude_ids = set(selected_config.get("exclude_ids") or [])
    since_dt = _parse_date(selected_config.get("include_after"))
    until_dt = _parse_date(selected_config.get("include_before"))
    scheme = selected_config.get("point_scheme") or "balanced"
    cutoff = _as_float(selected_config.get("qualification_cutoff"))

    title_text = f"{selected_label} Series Leaderboard"
    st.title(title_text)
    st.caption(
        f"Scheme: {scheme} | Include IDs: {len(include_ids)} | Exclude IDs: {len(exclude_ids)} "
        f"| Window: {_format_date(since_dt)} → {_format_date(until_dt)} "
        f"| Cutoff: {cutoff if cutoff is not None else '—'}"
    )
    note = selected_config.get("note")
    if note:
        st.info(note)

    with st.spinner("Loading tournaments from the database..."):
        tournaments = fetch_tournament_events_supabase(
            organizer,
            since=since_dt,
            until=until_dt,
            limit=200,
        )
        supabase_error = get_last_supabase_error() if not tournaments else None

    if not tournaments:
        if supabase_error:
            st.error(f"Database query failed: {supabase_error}")
        else:
            st.info("No tournaments found for this config.")
        return

    # Apply include/exclude filters from config
    if include_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") in include_ids]
    if exclude_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") not in exclude_ids]

    if not tournaments:
        st.info("No tournaments remain after applying include/exclude filters.")
        return

    event_ids = [t.get("tournament_id") for t in tournaments if t.get("tournament_id")]

    points_key = {
        "balanced": "points_balanced",
        "performance": "points_performance",
        "participation": "points_participation",
    }.get(scheme, "points_balanced")

    with st.spinner("Computing leaderboard..."):
        result_rows = fetch_tournament_results_supabase(
            tournament_ids=event_ids,
            organizer=organizer,
            since=since_dt,
            until=until_dt,
        )

    if not result_rows:
        st.info("No leaderboard rows found.")
        return

    totals_map: dict[str, dict[str, object]] = {}
    for row in result_rows:
        player = str(row.get("player") or "").strip()
        if not player:
            continue
        pts = _as_float(row.get(points_key)) or 0
        finish = row.get("finish")
        agg = totals_map.setdefault(
            player,
            {"points": 0.0, "events": 0, "finishes": [], "podiums": 0},
        )
        agg["points"] += pts
        agg["events"] += 1
        if finish is not None:
            agg["finishes"].append(finish)
            if isinstance(finish, (int, float)) and 1 <= float(finish) <= 3:
                agg["podiums"] += 1

    total_rows = []
    for player, agg in totals_map.items():
        finishes = [f for f in agg["finishes"] if f is not None]
        avg_finish = sum(finishes) / len(finishes) if finishes else None
        best_finish = min(finishes) if finishes else None
        total_rows.append(
            {
                "Player": player,
                "Points": agg["points"],
                "Events": agg["events"],
                "Avg Finish": avg_finish,
                "Best": best_finish,
                "Podiums": agg["podiums"],
            }
        )

    total_rows.sort(key=lambda r: r["Points"], reverse=True)
    df = pd.DataFrame(total_rows)
    styler = df.style
    if cutoff is not None and cutoff > 0:
        ticket_icon = "🎫"
        df.loc[df["Points"] >= cutoff, "Player"] = (
            ticket_icon + " " + df.loc[df["Points"] >= cutoff, "Player"].astype(str)
        )
        qualifying = df[df["Points"] >= cutoff]
        if not qualifying.empty:
            cutoff_idx = qualifying.index[-1]
            sentinel = {
                "Player": f"Cutoff at {cutoff:.0f} pts",
                "Points": None,
                "Events": None,
                "Avg Finish": None,
                "Best": None,
                "Podiums": None,
            }
            df = pd.concat(
                [df.iloc[: cutoff_idx + 1], pd.DataFrame([sentinel]), df.iloc[cutoff_idx + 1 :]],
                ignore_index=True,
            )
            mask = df["Player"].astype(str).str.startswith("Cutoff at")
            df.loc[mask, ["Points", "Events", "Avg Finish", "Best", "Podiums"]] = ""

            def _highlight_cutoff(row):
                if str(row.get("Player", "")).startswith("Cutoff at"):
                    return [
                        (
                            "background-color: #5f0000; color: #ffffff; font-weight: bold; "
                            "padding-top: 0px; padding-bottom: 0px; line-height: 0.7em; font-size: 0.9em;"
                        )
                    ] * len(row)
                return [""] * len(row)

            styler = df.style.apply(_highlight_cutoff, axis=1)
            st.caption(f"Red bar marks cutoff at {cutoff:.0f} points ({len(qualifying)} qualified).")
        else:
            st.caption(f"No entries meet the {cutoff:.0f}-point cutoff.")

    st.dataframe(
        styler,
        hide_index=True,
        width="stretch",
        height=_table_height_for_rows(len(df)),
        column_config={
            "Player": st.column_config.TextColumn(),
            "Points": st.column_config.NumberColumn(format="%.0f"),
            "Events": st.column_config.NumberColumn(format="%d"),
            "Avg Finish": st.column_config.NumberColumn(format="%.2f"),
            "Best": st.column_config.NumberColumn(format="%d"),
            "Podiums": st.column_config.NumberColumn(format="%d"),
        },
    )

    # Event list and single leaderboard view
    st.subheader("Events")
    rows = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        rows.append(
            {
                "Date": _format_date(start_dt),
                "Tournament": t.get("name") or t.get("tournament_id"),
            }
        )
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        height=_table_height_for_rows(len(rows), min_height=180, extra=90),
    )

    labels = [f"{row['Date']} - {row['Tournament']}" for row in rows]
    selected_label = st.selectbox("View event leaderboard", options=labels, index=0)
    selected_idx = labels.index(selected_label)
    selected_event = tournaments[selected_idx]
    tournament_id = selected_event.get("tournament_id")
    leaderboard = [r for r in result_rows if r.get("tournament_id") == tournament_id]

    st.subheader(f"Leaderboard: {selected_event.get('name') or tournament_id}")
    if leaderboard:
        st.dataframe(
            [
                {
                    "Finish": row.get("finish"),
                    "Player": row.get("player"),
                    "Points": _as_float(row.get(points_key)),
                    "Prizes": row.get("prize_text"),
                }
                for row in leaderboard
            ],
            hide_index=True,
            width="stretch",
            height=_table_height_for_rows(len(leaderboard), min_height=220, extra=100),
            column_config={
                "Finish": st.column_config.NumberColumn(format="%d"),
                "Player": st.column_config.TextColumn(),
                "Points": st.column_config.NumberColumn(format="%.0f"),
                "Prizes": st.column_config.TextColumn(),
            },
        )
    else:
        st.info("No leaderboard entries found for that event.")


if __name__ == "__main__":
    render_page()
