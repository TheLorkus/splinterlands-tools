from __future__ import annotations

import json
from datetime import datetime, date, timezone
import pandas as pd

import streamlit as st

from core.config import setup_page
from scholar_helper.services.api import fetch_hosted_tournaments, fetch_tournament_leaderboard
from scholar_helper.services.storage import (
    fetch_tournament_events_supabase,
    fetch_tournament_results_supabase,
    fetch_tournament_ingest_organizers,
    fetch_series_configs,
    fetch_point_schemes,
    get_last_supabase_error,
)


def setup_if_standalone() -> None:
    try:
        import streamlit as st  # type: ignore

        if not st.session_state.get("__series_tournament_setup_done"):
            setup_page("Tournament Series")
            st.session_state["__series_tournament_setup_done"] = True
    except Exception:
        pass


# Local fallback definitions in case point schemes are unavailable from the backend.
DEFAULT_POINT_SCHEMES = {
    "balanced": {
        "slug": "balanced",
        "label": "Balanced",
        "mode": "fixed",
        "base_points": 0,
        "dnp_points": 0,
        "rules": [
            {"min": 1, "max": 1, "points": 25},
            {"min": 2, "max": 2, "points": 18},
            {"min": 3, "max": 4, "points": 12},
            {"min": 5, "max": 8, "points": 8},
            {"min": 9, "max": 16, "points": 5},
            {"min": 17, "max": None, "points": 2},
        ],
    },
    "performance": {
        "slug": "performance",
        "label": "Performance-Focused",
        "mode": "fixed",
        "base_points": 0,
        "dnp_points": 0,
        "rules": [
            {"min": 1, "max": 1, "points": 50},
            {"min": 2, "max": 2, "points": 30},
            {"min": 3, "max": 3, "points": 20},
            {"min": 4, "max": 4, "points": 15},
            {"min": 5, "max": 8, "points": 10},
            {"min": 9, "max": 16, "points": 5},
            {"min": 17, "max": None, "points": 1},
        ],
    },
    "participation": {
        "slug": "participation",
        "label": "Participation",
        "mode": "multiplier",
        "base_points": 1,
        "dnp_points": 0,
        "rules": [
            {"min": 1, "max": 1, "multiplier": 3.0},
            {"min": 2, "max": 2, "multiplier": 2.5},
            {"min": 3, "max": 4, "multiplier": 2.0},
            {"min": 5, "max": 8, "multiplier": 1.5},
            {"min": 9, "max": 16, "multiplier": 1.2},
            {"min": 17, "max": None, "multiplier": 1.0},
        ],
    },
}


def _format_date(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d")


def _format_ruleset(allowed_cards: dict | None) -> str:
    if not isinstance(allowed_cards, dict):
        return "-"
    epoch = allowed_cards.get("epoch") or allowed_cards.get("type") or "Ruleset"
    ghost = allowed_cards.get("ghost")
    cards = allowed_cards.get("type") or "All"
    epoch_label = str(epoch).title()
    type_label = f"{epoch_label} {'Ghost' if ghost else 'Owned'}"
    cards_label = "All" if str(cards).lower() == "all" else str(cards).title()
    return f"Type: {type_label} - Cards: {cards_label}"


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


def _to_iso_date(value) -> str | None:
    dt = _parse_date(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _render_scheme_rules(scheme: dict) -> list[dict]:
    rules = scheme.get("rules") or []
    rows = []
    mode = scheme.get("mode")
    base_points = scheme.get("base_points")
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        row: dict = {
            "Min": rule.get("min"),
            "Max": rule.get("max"),
        }
        if mode == "multiplier":
            row["Base"] = base_points
            row["Multiplier"] = rule.get("multiplier")
        else:
            row["Points"] = rule.get("points")
        rows.append(row)
    return rows


def _resolve_scheme(scheme_map: dict[str, dict], slug: str) -> dict:
    """Pick the scheme definition by slug with a fallback to defaults."""
    return scheme_map.get(slug) or DEFAULT_POINT_SCHEMES.get(slug, {})


def _calculate_points_for_finish(finish: int | None, scheme: dict) -> float | None:
    """Mirror the backend calculate_points_for_finish() logic in Python."""
    if not scheme:
        return None
    mode = str(scheme.get("mode") or "fixed").lower()
    base_points = float(scheme.get("base_points") or 0)
    dnp_points = float(scheme.get("dnp_points") or 0)
    rules = scheme.get("rules") or []
    if finish is None:
        return dnp_points
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        min_place = rule.get("min")
        max_place = rule.get("max")
        if min_place is None:
            continue
        try:
            min_val = int(min_place)
            max_val = int(max_place) if max_place is not None else None
        except Exception:
            continue
        if finish < min_val:
            continue
        if max_val is not None and finish > max_val:
            continue
        if mode == "multiplier":
            multiplier = float(rule.get("multiplier") or 1)
            return base_points * multiplier
        points = float(rule.get("points") or 0)
        return base_points + points
    return dnp_points


def _fetch_tournaments_from_api(
    organizer: str, since: datetime | None, until: datetime | None, limit: int
) -> list[dict]:
    """Live fallback: pull hosted tournaments directly from the Splinterlands API."""
    try:
        hosted = fetch_hosted_tournaments(organizer)
    except Exception:
        return []
    filtered: list[dict] = []
    for t in hosted:
        start_date = t.start_date
        if since and start_date and start_date < since:
            continue
        if until and start_date and start_date > until:
            continue
        filtered.append(
            {
                "tournament_id": t.id,
                "organizer": organizer,
                "name": t.name,
                "start_date": t.start_date,
                "allowed_cards": t.allowed_cards,
                "payouts": t.payouts,
                "raw": t.raw,
            }
        )
    if limit and len(filtered) > limit:
        filtered = filtered[:limit]
    return filtered


def _fetch_results_from_api(
    tournaments: list[dict],
    organizer: str,
    points_key: str,
    scheme: dict,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """
    Pull player results from the API and compute points locally for custom organizers.
    Returns (flat list, by_event_id map).
    """
    all_rows: list[dict] = []
    by_event: dict[str, list[dict]] = {}
    for t in tournaments:
        tid = t.get("tournament_id")
        if not tid:
            continue
        payouts = t.get("payouts") or []
        try:
            leaderboard = fetch_tournament_leaderboard(tid, organizer, payouts=payouts)
        except Exception:
            leaderboard = []
        for entry in leaderboard:
            if not isinstance(entry, dict):
                continue
            finish = entry.get("finish")
            try:
                finish_val = int(finish) if finish is not None else None
            except Exception:
                finish_val = None
            points = _calculate_points_for_finish(finish_val, scheme)
            row = {
                "tournament_id": tid,
                "player": entry.get("player"),
                "finish": finish_val,
                "prize_text": entry.get("prize") or entry.get("prize_text"),
                points_key: points,
            }
            all_rows.append(row)
            by_event.setdefault(tid, []).append(row)
    return all_rows, by_event


def render_page(embed_mode: bool = False) -> None:
    if not embed_mode:
        setup_if_standalone()
        st.title("Tournament Series")
        st.caption("Stored list of hosted tournaments with cached leaderboards.")

    organizers = fetch_tournament_ingest_organizers()
    col_org_1, col_org_2 = st.columns(2)
    with col_org_1:
        selected_org = st.selectbox(
            "Organizer (known list)",
            options=organizers if organizers else ["(none)"],
            index=0,
            help="Pick a seeded organizer or type any username to load tournaments.",
        )
    with col_org_2:
        typed_username = st.text_input(
            "Or type any organizer username",
            placeholder="e.g., sps.tournaments",
            help="Press Enter or click Load to fetch tournaments from the database/API.",
        ).strip()
    load_clicked = st.button("Load tournaments", type="primary")

    username = typed_username or (selected_org if selected_org and selected_org != "(none)" else "")

    if load_clicked and not username:
        st.warning("Enter or select an organizer, then click Load.")
        return

    configs = fetch_series_configs(username) if username else []
    config_labels = ["(No saved config)"] + [cfg.get("name") or str(cfg.get("id")) for cfg in configs]
    selected_config_label = st.selectbox("Series config (optional)", options=config_labels, index=0)
    selected_config = None

    if not username:
        st.info("Enter an organizer username to view hosted tournaments.")
        return

    scheme_options = {
        "Balanced": "balanced",
        "Performance": "performance",
        "Participation": "participation",
    }

    col1, col2, col3 = st.columns(3)
    with col1:
        scheme_label = st.selectbox("Point scheme", options=list(scheme_options.keys()), index=0)
        scheme = scheme_options[scheme_label]
    with col2:
        name_filter = st.text_input("Tournament name (optional, partial match)", value="")
    with col3:
        since_date = st.date_input("Start date (optional)", value=None)
        until_date = st.date_input("End date (optional)", value=None)

    # Apply config overrides if selected.
    include_ids: list[str] = []
    exclude_ids: set[str] = set()
    if selected_config_label != "(No saved config)" and configs:
        selected_config = next(
            (c for c in configs if (c.get("name") or str(c.get("id"))) == selected_config_label),
            None,
        )
        if selected_config:
            scheme = selected_config.get("point_scheme") or scheme
            since_date = selected_config.get("include_after") or since_date
            until_date = selected_config.get("include_before") or until_date
            name_filter = selected_config.get("name_filter") or name_filter
            include_ids = selected_config.get("include_ids") or []
            exclude_ids = set(selected_config.get("exclude_ids") or [])
            # Normalize label to match the overridden scheme.
            scheme_label = next((label for label, slug in scheme_options.items() if slug == scheme), scheme_label)

    schemes = fetch_point_schemes()
    scheme_map = {s.get("slug"): s for s in schemes} if schemes else {}
    scheme_def = _resolve_scheme(scheme_map, scheme)

    limit = st.slider("Limit to last N events (0 = all after filters)", min_value=0, max_value=100, value=20)

    source = "supabase"
    results_by_event: dict[str, list[dict]] = {}
    with st.spinner(f"Loading tournaments ingested for {username}..."):
        tournaments = fetch_tournament_events_supabase(
            username,
            since=_parse_date(since_date),
            until=_parse_date(until_date),
            limit=200,
        )
    supabase_error = get_last_supabase_error() if not tournaments else None

    # Live API fallback for any organizer when the database has no rows yet.
    if not tournaments and username:
        with st.spinner(f"Fetching tournaments for {username} from Splinterlands..."):
            tournaments = _fetch_tournaments_from_api(
                organizer=username,
                since=_parse_date(since_date),
                until=_parse_date(until_date),
                limit=200,
            )
        if tournaments:
            source = "api"
            supabase_error = None

    if not tournaments:
        if supabase_error:
            st.error(f"Database query failed: {supabase_error}")
        else:
            st.info("No tournaments found for that organizer. Ingest first, then refresh.")
        return
    else:
        if source == "api":
            st.info(
                "Using live Splinterlands API data for this organizer (not yet stored). "
                "Points are computed locally with the selected scheme."
            )
        else:
            st.caption("Loaded tournaments from stored data.")

    # Optional ruleset filter derived from available allowed_cards.
    ruleset_labels = sorted({(_format_ruleset(t.get("allowed_cards")) or "-") for t in tournaments})
    ruleset_labels = [label for label in ruleset_labels if label and label != "-"]
    ruleset_labels.insert(0, "All rulesets")
    selected_ruleset = st.selectbox("Ruleset filter (optional)", options=ruleset_labels, index=0)
    if selected_ruleset != "All rulesets":
        tournaments = [t for t in tournaments if _format_ruleset(t.get("allowed_cards")) == selected_ruleset]
        if not tournaments:
            st.info("No tournaments match that ruleset for the selected filters.")
            return

    if name_filter:
        name_lower = name_filter.lower()
        tournaments = [
            t for t in tournaments if name_lower in str(t.get("name") or t.get("tournament_id") or "").lower()
        ]
        if not tournaments:
            st.info("No tournaments match that name for the selected filters.")
            return

    # Filter by include/exclude ids from config.
    if include_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") in include_ids]
    if exclude_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") not in exclude_ids]

    # Trim to last N after filtering.
    if limit and len(tournaments) > limit:
        tournaments = tournaments[:limit]

    rows = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        rows.append(
            {
                "Date": _format_date(start_dt),
                "Tournament": t.get("name") or t.get("tournament_id"),
                "Ruleset": _format_ruleset(t.get("allowed_cards")),
            }
        )

    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "Date": st.column_config.TextColumn(),
            "Tournament": st.column_config.TextColumn(),
            "Ruleset": st.column_config.TextColumn(),
            },
        )

    # Series leaderboard
    points_key = {
        "balanced": "points_balanced",
        "performance": "points_performance",
        "participation": "points_participation",
    }.get(scheme, "points_balanced")

    event_ids = [t.get("tournament_id") for t in tournaments if t.get("tournament_id")]

    if source == "supabase":
        with st.spinner("Computing series leaderboard..."):
            result_rows = fetch_tournament_results_supabase(
                tournament_ids=event_ids,
                organizer=username,
                since=_parse_date(since_date),
                until=_parse_date(until_date),
            )
    else:
        with st.spinner("Computing series leaderboard from live API..."):
            result_rows, results_by_event = _fetch_results_from_api(
                tournaments,
                organizer=username,
                points_key=points_key,
                scheme=scheme_def,
            )

    if result_rows:
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
        ruleset_title = "Full"
        if name_filter:
            ruleset_title = name_filter.strip().capitalize()
        elif selected_ruleset != "All rulesets":
            ruleset_title = selected_ruleset
            if ruleset_title.lower().startswith("type:"):
                ruleset_title = ruleset_title.replace("Type:", "").strip()
            ruleset_title = ruleset_title.split(" - ")[0].strip() or "Full"
        tournament_count = len(tournaments)
        tabs = st.tabs(["Leaderboard", "Point schemes"])
        with tabs[0]:
            st.subheader(
                f"{ruleset_title} Series Leaderboard hosted by {username} ({scheme_label} points) - aggregated over {tournament_count} tournaments"
            )
            threshold = st.number_input(
                f"Qualification threshold ({scheme_label} points)",
                min_value=0.0,
                value=0.0,
                step=1.0,
                help="Draw a red line showing who meets the cutoff.",
            )
            df = pd.DataFrame(total_rows)
            styler = df.style
            if threshold > 0:
                # Ticket marker for qualifiers (emoji color depends on platform; 🎫 is usually gold/yellow).
                ticket_icon = "🎫"
                df.loc[df["Points"] >= threshold, "Player"] = (
                    ticket_icon + " " + df.loc[df["Points"] >= threshold, "Player"].astype(str)
                )
                qualifying = df[df["Points"] >= threshold]
                if not qualifying.empty:
                    cutoff_idx = qualifying.index[-1]
                    sentinel = {
                        "Player": f"Cutoff at {threshold:.0f} pts",
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
                    st.caption(
                        f"Red bar marks cutoff at {threshold:.0f} points ({len(qualifying)} qualified)."
                    )
                else:
                    st.caption(f"No entries meet the {threshold:.0f}-point threshold.")
            st.dataframe(
                styler,
                hide_index=True,
                width="stretch",
                column_config={
                    "Player": st.column_config.TextColumn(),
                    "Points": st.column_config.NumberColumn(format="%.0f"),
                    "Events": st.column_config.NumberColumn(format="%d"),
                    "Avg Finish": st.column_config.NumberColumn(format="%.2f"),
                    "Best": st.column_config.NumberColumn(format="%d"),
                    "Podiums": st.column_config.NumberColumn(format="%d"),
                },
            )
        with tabs[1]:
            st.subheader("Point Schemes")
            schemes_for_tab = schemes or fetch_point_schemes()
            if not schemes_for_tab:
                st.info("No point schemes found in the backend.")
            else:
                for scheme_obj in schemes_for_tab:
                    st.markdown(f"**{scheme_obj.get('label') or scheme_obj.get('slug')}** ({scheme_obj.get('mode')})")
                    st.caption(
                        f"Base points: {scheme_obj.get('base_points')}, DNP points: {scheme_obj.get('dnp_points')}"
                    )
                    rows = _render_scheme_rules(scheme_obj)
                    st.dataframe(
                        rows,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Min": st.column_config.NumberColumn(format="%d"),
                            "Max": st.column_config.NumberColumn(format="%d"),
                            "Base": st.column_config.NumberColumn(format="%.0f"),
                            "Multiplier": st.column_config.NumberColumn(format="%.2f"),
                            "Points": st.column_config.NumberColumn(format="%.0f"),
                        },
                    )
                    st.divider()
    else:
        st.info("No leaderboard rows found for the selected window.")

    labels = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        labels.append(f"{_format_date(start_dt)} - {t.get('name') or t.get('tournament_id')}")
    if not labels:
        return

    selected_label = st.selectbox("View leaderboard", options=labels, index=0)

    selected_idx = labels.index(selected_label)
    selected = tournaments[selected_idx]
    tournament_id = selected.get("tournament_id") or selected.get("id")
    if source == "supabase":
        with st.spinner(f"Loading leaderboard for {selected.get('name') or tournament_id}..."):
            leaderboard = fetch_tournament_results_supabase(tournament_id)
    else:
        leaderboard = results_by_event.get(tournament_id) or []
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
            column_config={
                "Finish": st.column_config.NumberColumn(format="%d"),
                "Player": st.column_config.TextColumn(),
                "Points": st.column_config.NumberColumn(format="%.0f"),
                "Prizes": st.column_config.TextColumn(),
            },
        )
    else:
        st.info("No leaderboard entries found for that tournament.")

    st.divider()
    include_after_iso = _to_iso_date(since_date)
    include_before_iso = _to_iso_date(until_date)
    config_payload = {
        "name": (selected_config.get("name") if selected_config else None) or "(name this config)",
        "organizer": username,
        "point_scheme": scheme,
        "name_filter": name_filter or (selected_config.get("name_filter") if selected_config else None) or "",
        "include_ids": list(include_ids) if include_ids else [],
        "exclude_ids": sorted(exclude_ids) if exclude_ids else [],
        "include_after": include_after_iso,
        "include_before": include_before_iso,
        "visibility": (selected_config.get("visibility") if selected_config else None) or "public",
        "note": selected_config.get("note") if selected_config else None,
        "qualification_cutoff": selected_config.get("qualification_cutoff") if selected_config else None,
    }
    st.subheader("Copy/paste series config")
    st.caption("Use this JSON payload to insert into series_configs via your backend or helper scripts.")
    st.code(json.dumps(config_payload, indent=2), language="json")


if __name__ == "__main__":
    render_page()
