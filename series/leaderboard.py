from __future__ import annotations

import html
import warnings
from datetime import date, datetime
from typing import TypedDict

import pandas as pd
import streamlit as st

from core.config import setup_page
from scholar_helper.services.storage import (
    fetch_reward_cards,
    fetch_series_configs,
    fetch_tournament_events_supabase,
    fetch_tournament_results_supabase,
    fetch_tournament_rewards_for_tournament_ids,
    fetch_tournament_rewards_supabase,
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


def _tournament_detail_url(tournament_id: object) -> str | None:
    if tournament_id is None:
        return None
    tid = str(tournament_id).strip()
    if not tid:
        return None
    return f"https://next.splinterlands.com/tournament/detail/{tid}"


def _format_tournament_cell(name: str, url: str | None) -> str:
    safe_name = html.escape(name)
    if url:
        safe_url = html.escape(url, quote=True)
        return f"{safe_name} - " f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">Link</a>'
    return safe_name


def _render_events_table(rows: list[dict[str, str]]) -> None:
    header_cells = "<th>Date</th><th>Tournament</th><th>Tournament ID</th>"
    body_rows = []
    for row in rows:
        date_text = html.escape(row.get("Date", "") or "")
        tournament_cell = row.get("Tournament", "")
        tournament_id = html.escape(row.get("Tournament ID", "") or "")
        body_rows.append(f"<tr><td>{date_text}</td><td>{tournament_cell}</td><td>{tournament_id}</td></tr>")

    table_html = f"""
    <style>
    .sl-events-table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .sl-events-table th,
    .sl-events-table td {{
        padding: 0.35rem 0.5rem;
        border-bottom: 1px solid rgba(49, 51, 63, 0.2);
        text-align: left;
        vertical-align: top;
    }}
    .sl-events-table a {{
        color: inherit;
        text-decoration: underline;
    }}
    </style>
    <table class="sl-events-table">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{"".join(body_rows)}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def render_page(embed_mode: bool = False) -> None:
    if not embed_mode:
        setup_if_standalone()
        st.title("Tournament Series")
        st.caption("Pick an organizer and config to view its saved series leaderboard.")

    params = st.query_params

    def _coerce_param(value):
        if isinstance(value, list):
            return value[0] if value else None
        return value

    default_org = _coerce_param(params.get("organizer")) or _coerce_param(params.get("org")) or "lorkus"
    default_config = _coerce_param(params.get("config")) or _coerce_param(params.get("name")) or _coerce_param(params.get("id")) or "Delegated & Dangerous"

    organizer = st.text_input("Organizer", value=default_org, placeholder="e.g., lorkus or clove71").strip()
    if not organizer:
        st.info("Enter an organizer to load their saved series configs.")
        return
    if _coerce_param(params.get("organizer")) != organizer:
        params["organizer"] = organizer

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
    config_param_value = str(selected_config.get("id") or selected_label)
    if _coerce_param(params.get("config")) != config_param_value:
        params["config"] = config_param_value

    # Extract filters from config (coerce to concrete types for type-checkers)
    include_ids_raw = selected_config.get("include_ids")
    include_ids: list[str] = []
    if isinstance(include_ids_raw, list):
        include_ids = [str(v) for v in include_ids_raw if v is not None and str(v).strip()]

    exclude_ids_raw = selected_config.get("exclude_ids")
    exclude_ids: set[str] = set()
    if isinstance(exclude_ids_raw, list):
        exclude_ids = {str(v) for v in exclude_ids_raw if v is not None and str(v).strip()}

    since_dt = _parse_date(selected_config.get("include_after"))
    until_dt = _parse_date(selected_config.get("include_before"))
    scheme = str(selected_config.get("point_scheme") or "balanced")
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

    event_ids: list[str] = [str(t.get("tournament_id")) for t in tournaments if t.get("tournament_id")]

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

    # Optional: series-wide delegated cards (only for organizer "lorkus")
    delegations_by_player: dict[str, str] = {}
    if organizer.strip().lower() == "lorkus" and event_ids:
        reward_rows = fetch_tournament_rewards_for_tournament_ids(event_ids)
        card_rows = fetch_reward_cards(enabled_only=False)

        card_name_by_id: dict[object, str] = {}
        for c in card_rows:
            cid = c.get("reward_card_id")
            name = c.get("name")
            if cid is not None and isinstance(name, str) and name.strip():
                card_name_by_id[cid] = name.strip()

        order_idx = {tid: i for i, tid in enumerate(event_ids)}
        tmp: dict[str, list[tuple[int, str]]] = {}
        for r in reward_rows:
            tid = r.get("tournament_id")
            player_raw = r.get("player")
            cid = r.get("reward_card_id")
            if not isinstance(player_raw, str) or not player_raw.strip():
                continue
            if tid is None or cid is None:
                continue
            name = card_name_by_id.get(cid)
            if not name:
                continue
            tid_str = str(tid)
            idx = order_idx.get(tid_str, 10**9)
            key = player_raw.strip().lower()
            tmp.setdefault(key, []).append((idx, name))

        for p, items in tmp.items():
            items.sort(key=lambda t: t[0])
            delegations_by_player[p] = ", ".join([nm for _, nm in items])

    if not result_rows:
        st.info("No leaderboard rows found.")
        return

    class _PlayerAgg(TypedDict):
        points: float
        events: int
        finishes: list[float]
        podiums: int

    totals_map: dict[str, _PlayerAgg] = {}
    for row in result_rows:
        player = str(row.get("player") or "").strip()
        if not player:
            continue
        pts = _as_float(row.get(points_key)) or 0.0
        finish = _as_float(row.get("finish"))

        agg = totals_map.get(player)
        if agg is None:
            new_agg: _PlayerAgg = {"points": 0.0, "events": 0, "finishes": [], "podiums": 0}
            totals_map[player] = new_agg
            agg = new_agg

        agg["points"] += float(pts)
        agg["events"] += 1
        if finish is not None:
            agg["finishes"].append(float(finish))
            if 1 <= finish <= 3:
                agg["podiums"] += 1

    total_rows = []
    for player, agg in totals_map.items():
        finishes = agg["finishes"]
        avg_finish = sum(finishes) / len(finishes) if finishes else None
        best_finish = int(min(finishes)) if finishes else None
        total_rows.append(
            {
                "Player": player,
                "Card delegations": delegations_by_player.get(player.strip().lower(), "") if organizer.strip().lower() == "lorkus" else "",
                "Points": agg["points"],
                "Events": agg["events"],
                "Avg Finish": avg_finish,
                "Best": best_finish,
                "Podiums": agg["podiums"],
            }
        )

    if organizer.strip().lower() == "lorkus":
        columns = ["Player", "Card delegations", "Points", "Events", "Avg Finish", "Best", "Podiums"]
    else:
        columns = ["Player", "Points", "Events", "Avg Finish", "Best", "Podiums"]

    total_rows.sort(key=lambda r: r["Points"], reverse=True)
    qualifying_count = 0
    if cutoff is not None and cutoff > 0:
        ticket_icon = "🎫"
        qualifying_indexes = []
        for idx, row in enumerate(total_rows):
            points = row.get("Points")
            if points is not None and points >= cutoff:
                row["Player"] = f"{ticket_icon} {row.get('Player')}"
                qualifying_indexes.append(idx)
        qualifying_count = len(qualifying_indexes)
        if qualifying_indexes:
            cutoff_idx = qualifying_indexes[-1]
            total_rows.insert(
                cutoff_idx + 1,
                {
                    "Player": f"Cutoff at {cutoff:.0f} pts",
                    "Points": None,
                    "Events": None,
                    "Avg Finish": None,
                    "Best": None,
                    "Podiums": None,
                },
            )

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=("The behavior of DataFrame concatenation with empty or all-NA entries is deprecated.*"),
            category=FutureWarning,
        )
        df = pd.DataFrame.from_records(total_rows, columns=columns)
    styler = df.style
    if cutoff is not None and cutoff > 0:
        if qualifying_count:

            def _highlight_cutoff(row):
                if str(row.get("Player", "")).startswith("Cutoff at"):
                    return [("background-color: #5f0000; color: #ffffff; font-weight: bold; padding-top: 0px; padding-bottom: 0px; line-height: 0.7em; font-size: 0.9em;")] * len(row)
                return [""] * len(row)

            styler = df.style.apply(_highlight_cutoff, axis=1)
            st.caption(f"Red bar marks cutoff at {cutoff:.0f} points ({qualifying_count} qualified).")
        else:
            st.caption(f"No entries meet the {cutoff:.0f}-point cutoff.")

    st.dataframe(
        styler,
        hide_index=True,
        width="stretch",
        height=_table_height_for_rows(len(df)),
        column_config={
            "Player": st.column_config.TextColumn(),
            "Card delegations": st.column_config.TextColumn(),
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
    display_rows = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        tid = t.get("tournament_id")
        name_raw = str(t.get("name") or "").strip()
        tournament_name = name_raw or (str(tid).strip() if tid is not None else "-")
        tournament_url = _tournament_detail_url(tid)
        rows.append(
            {
                "Date": _format_date(start_dt),
                "Tournament": tournament_name,
                "Tournament ID": tid,
            }
        )
        display_rows.append(
            {
                "Date": _format_date(start_dt),
                "Tournament": _format_tournament_cell(tournament_name, tournament_url),
                "Tournament ID": str(tid).strip() if tid is not None else "-",
            }
        )
    _render_events_table(display_rows)

    labels = [f"{row['Date']} - {row['Tournament']}" for row in rows]
    selected_label = st.selectbox("View event leaderboard", options=labels, index=0)
    selected_idx = labels.index(selected_label)
    selected_event = tournaments[selected_idx]
    tournament_id = selected_event.get("tournament_id")
    leaderboard = [r for r in result_rows if r.get("tournament_id") == tournament_id]

    reward_map: dict[str, str] = {}
    if organizer.strip().lower() == "lorkus" and tournament_id:
        reward_rows_single = fetch_tournament_rewards_supabase(str(tournament_id))
        card_rows_single = fetch_reward_cards(enabled_only=False)
        card_name_by_id_single: dict[object, str] = {}
        for c in card_rows_single:
            cid = c.get("reward_card_id")
            name = c.get("name")
            if cid is not None and isinstance(name, str) and name.strip():
                card_name_by_id_single[cid] = name.strip()
        for r in reward_rows_single:
            player_raw = r.get("player")
            cid = r.get("reward_card_id")
            if not isinstance(player_raw, str) or not player_raw.strip():
                continue
            if cid is None:
                continue
            nm = card_name_by_id_single.get(cid)
            if nm:
                reward_map[player_raw.strip().lower()] = nm

    st.subheader(f"Leaderboard: {selected_event.get('name') or tournament_id}")
    if leaderboard:
        st.dataframe(
            [
                {
                    "Finish": row.get("finish"),
                    "Player": row.get("player"),
                    "Card delegation": reward_map.get(str(row.get("player") or "").strip().lower(), "") if organizer.strip().lower() == "lorkus" else "",
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
                "Card delegation": st.column_config.TextColumn(),
                "Points": st.column_config.NumberColumn(format="%.0f"),
                "Prizes": st.column_config.TextColumn(),
            },
        )
    else:
        st.info("No leaderboard entries found for that event.")


if __name__ == "__main__":
    render_page()
