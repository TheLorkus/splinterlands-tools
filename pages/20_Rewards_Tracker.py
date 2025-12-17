from __future__ import annotations

from typing import Dict, List
import streamlit as st

from core.config import render_footer, setup_page
from features.scholar.service import (
    aggregate_totals,
    cached_prices,
    cached_rewards,
    cached_season,
    cached_tournaments,
    clear_caches,
    fetch_season_history,
    filter_tournaments_for_season,
    get_supabase_client,
    parse_usernames,
    update_season_currency,
    _aggregated_totals_from_record,
    _build_currency_options,
    _format_price,
    _format_scholar_payout,
    _format_token_amounts_dict,
    _get_finish_for_tournament,
    _merge_token_amounts,
    _parse_token_amounts,
    _record_scholar_pct,
    _record_season_id,
    _safe_float,
    _sum_rewards_usd,
)
from scholar_helper.models import AggregatedTotals, CategoryTotals, RewardEntry, TournamentResult


setup_page("Rewards Tracker")


def _entry_fee_to_tokens(entry_fee) -> dict[str, float]:
    """Convert a TokenAmount-like entry_fee to a dict[str, float] for display."""
    if entry_fee is None:
        return {}
    token = getattr(entry_fee, "token", None)
    amount = getattr(entry_fee, "amount", None)
    if token is None or amount is None:
        return {}
    return {str(token).upper(): float(amount)}


def _token_amounts_from_rewards(rewards) -> dict[str, float]:
    """Convert a list of reward token objects to a dict for display."""
    tokens: dict[str, float] = {}
    if not rewards:
        return tokens
    for reward in rewards:
        token = getattr(reward, "token", None)
        amount = getattr(reward, "amount", None)
        if token is None or amount is None:
            continue
        tokens[str(token).upper()] = tokens.get(str(token).upper(), 0.0) + float(amount)
    return tokens


def render_page():
    st.title("Rewards Tracker")
    st.caption("Account-centric rewards. Toggle Scholar mode for payout tools and history.")

    try:
        season = cached_season()
        prices = cached_prices()
    except Exception as exc:
        st.error(f"Failed to load base data: {exc}")
        return

    price_tokens = ["USD", "SPS", "DEC", "ETH", "HIVE", "BTC", "VOUCHER"]
    price_rows = []
    for token in price_tokens:
        if token.upper() == "USD":
            display = "$1.00"
        else:
            price = prices.get(token.lower())
            display = _format_price(price) if price is not None else "-"
        price_rows.append({"Currency": token, "USD price": display})
    with st.sidebar:
        st.subheader("Mode")
        scholar_mode = st.toggle("Scholar mode", value=False, help="Enable scholar payouts/history")
        st.subheader("Prices")
        st.dataframe(
            price_rows,
            hide_index=True,
            column_config={
                "Currency": st.column_config.TextColumn(),
                "USD price": st.column_config.TextColumn(),
            },
        )
    st.write(f"Season {season.id}: {season.starts.date()} \u2192 {season.ends.date()}")

    tab_labels = ["Summary", "Tournaments"]
    if scholar_mode:
        tab_labels.append("Scholar history")
    tabs = st.tabs(tab_labels)
    tab_summary = tabs[0]
    tab_tournaments = tabs[1]
    tab_history = tabs[2] if scholar_mode else None

    with tab_summary:
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            usernames_raw = st.text_input("Usernames (comma separated)", value="")
        with col2:
            scholar_pct = (
                st.number_input("Scholar share (%)", min_value=0, max_value=100, value=0, step=5)
                if scholar_mode
                else 0
            )
        with col3:
            refresh_clicked = st.button("Refresh now")

        if refresh_clicked:
            clear_caches()
            st.rerun()

        usernames = parse_usernames(usernames_raw)

        per_user_totals: List[tuple[str, AggregatedTotals]] = []
        reward_rows: List[RewardEntry] = []
        tournament_rows: List[TournamentResult] = []
        user_tournaments_by_user: Dict[str, List[TournamentResult]] = {}
        currency_choices: Dict[int, str] = {}
        default_currency = "SPS"
        currency_options: List[str] = ["SPS"]

        for username in usernames:
            with st.spinner(f"Fetching data for {username}..."):
                try:
                    user_rewards = cached_rewards(username)
                    user_tournaments = cached_tournaments(username)
                except Exception as exc:
                    st.warning(f"Failed to fetch data for {username}: {exc}")
                    continue

                # Attach username to results for downstream display.
                for reward in user_rewards:
                    if not hasattr(reward, "username"):
                        setattr(reward, "username", username)
                for tournament in user_tournaments:
                    if not hasattr(tournament, "username"):
                        setattr(tournament, "username", username)

                reward_rows.extend(user_rewards)
                tournament_rows.extend(user_tournaments)
                user_tournaments_by_user[username] = user_tournaments

                try:
                    totals = aggregate_totals(season, user_rewards, user_tournaments, prices)
                    per_user_totals.append((username, totals))
                except Exception as exc:
                    st.warning(f"Failed to aggregate data for {username}: {exc}")

        if not reward_rows and not tournament_rows:
            st.info("No data found yet. Try adding usernames.")
            return

        combined_totals: AggregatedTotals = aggregate_totals(season, reward_rows, tournament_rows, prices)

        if per_user_totals:
            st.markdown("### Per-user totals")
            per_user_rows = []
            for username, totals in per_user_totals:
                per_user_rows.append(
                    {
                        "User": username,
                        "Overall (USD)": totals.overall.usd,
                        "Ranked (USD)": totals.ranked.usd,
                        "Brawl (USD)": totals.brawl.usd,
                        "Tournament (USD)": totals.tournament.usd,
                    }
                )
            st.dataframe(
                per_user_rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "Overall (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Ranked (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Brawl (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Tournament (USD)": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            if scholar_mode:
                currency_options = _build_currency_options(per_user_totals)
                st.markdown("#### Scholar payout currency per account")
                selector_columns_count = max(1, min(2, len(per_user_totals)))
                selector_columns = st.columns(selector_columns_count)
                default_currency_idx = currency_options.index("SPS") if "SPS" in currency_options else 0
                currency_choices: dict[int, str] = {}
                for idx, (username, _) in enumerate(per_user_totals):
                    selection_column = selector_columns[idx % selector_columns_count]
                    currency_choices[idx] = selection_column.selectbox(
                        f"{username} payout currency",
                        options=currency_options,
                        key=f"scholar_payout_currency_{idx}_{username}",
                        index=default_currency_idx,
                    )

                st.markdown("#### Scholar + owner share table")
                default_currency = currency_options[default_currency_idx]
                table_rows = []
                for idx, (username, user_totals) in enumerate(per_user_totals):
                    scholar_share_usd = user_totals.overall.usd * (scholar_pct / 100)
                    owner_share_usd = user_totals.overall.usd - scholar_share_usd
                    scholar_share_sps = user_totals.overall.token_amounts.get("SPS", 0) * (scholar_pct / 100)
                    selected_currency = currency_choices.get(idx, default_currency)
                    payout_display = _format_scholar_payout(selected_currency, user_totals, scholar_pct, prices)
                    table_rows.append(
                        {
                            "User": username,
                            "Overall (USD)": user_totals.overall.usd,
                            "Ranked (USD)": user_totals.ranked.usd,
                            "Brawl (USD)": user_totals.brawl.usd,
                            "Tournament (USD)": user_totals.tournament.usd,
                            "Scholar share (USD)": scholar_share_usd,
                            "Owner share (USD)": owner_share_usd,
                            "Scholar share (SPS)": scholar_share_sps,
                            "Scholar payout": payout_display,
                        }
                    )
                st.dataframe(
                    table_rows,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Overall (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Ranked (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Brawl (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Tournament (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Scholar share (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Owner share (USD)": st.column_config.NumberColumn(format="%.2f"),
                        "Scholar share (SPS)": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

        st.markdown("### Rewards by source (all users, season)")
        source_rows = [
            {"Source": "Ranked", "USD (est)": combined_totals.ranked.usd, "Tokens": _format_token_amounts_dict(combined_totals.ranked.token_amounts, prices)},
            {"Source": "Brawl", "USD (est)": combined_totals.brawl.usd, "Tokens": _format_token_amounts_dict(combined_totals.brawl.token_amounts, prices)},
            {"Source": "Tournament", "USD (est)": combined_totals.tournament.usd, "Tokens": _format_token_amounts_dict(combined_totals.tournament.token_amounts, prices)},
            {"Source": "Entry fees (tracking)", "USD (est)": combined_totals.entry_fees.usd, "Tokens": _format_token_amounts_dict(combined_totals.entry_fees.token_amounts, prices)},
        ]
        st.dataframe(
            source_rows,
            width="stretch",
            hide_index=True,
            column_config={
                "USD (est)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    with tab_tournaments:
        st.markdown("### Tournament lookup")
        lookup_username = st.text_input(
            "Tournament username", value=(usernames[0] if usernames else "")
        )
        if lookup_username.strip():
            with st.spinner(f"Loading tournaments for {lookup_username}..."):
                user_tournaments = cached_tournaments(lookup_username)
                for t in user_tournaments:
                    setattr(t, "username", lookup_username)
            if not user_tournaments:
                st.info("No tournaments found for that user.")
            else:
                tournaments_this_season = filter_tournaments_for_season(user_tournaments, season)
                display_rows = []
                total_prize_usd = 0.0
                for t in tournaments_this_season:
                    finish_value = _get_finish_for_tournament(t, lookup_username)
                    if finish_value in (None, "-"):
                        continue
                    usd_value = _sum_rewards_usd(t.rewards, prices)
                    total_prize_usd += usd_value
                    tournament_name = t.name or t.raw.get("title", "-")
                    display_rows.append(
                        {
                            "Tournament": tournament_name,
                            "Start": t.start_date.date() if t.start_date else "-",
                            "Finish": finish_value,
                            "Prize": _format_token_amounts_dict(
                                _token_amounts_from_rewards(getattr(t, "rewards", None)), prices
                            ),
                            "Entry fee": _format_token_amounts_dict(
                                _entry_fee_to_tokens(getattr(t, "entry_fee", None)), prices
                            ),
                        }
                    )
                if display_rows:
                    st.metric("Total tournament earnings (USD est)", f"${total_prize_usd:,.2f}")
                    st.dataframe(
                        display_rows,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Prize": st.column_config.TextColumn("Prize"),
                            "Entry fee": st.column_config.TextColumn("Entry fee"),
                        },
                    )
                else:
                    st.info("No tournaments for this user in the current season.")
        else:
            st.info("Enter a username to view tournament history.")

    if scholar_mode and tab_history is not None:
        with tab_history:
            st.markdown("### Saved history (season totals)")
            supabase_client = get_supabase_client()
            if supabase_client is None:
                st.warning("Database is not configured. Check environment variables or connectivity.")
            else:
                history_username_raw = st.text_input("History username", value="")
                normalized_history_username = history_username_raw.lower().strip()
                history_currency_options = ["SPS", "USD", "DEC", "ETH", "HIVE", "BTC", "VOUCHER"]
                feedback_key = f"history_feedback_{normalized_history_username}"

                if feedback_key in st.session_state:
                    st.success(st.session_state[feedback_key])
                    del st.session_state[feedback_key]

                if not normalized_history_username:
                    st.info("Enter a username to load saved history.")
                    return

                with st.spinner("Loading history from the database..."):
                    records = fetch_season_history(normalized_history_username)
                if not records:
                    st.info("No season history found for that user.")
                    return

                filtered_records: list[dict] = []
                for rec in records:
                    usernames_field = rec.get("username") or rec.get("usernames")
                    names: list[str] = []
                    if isinstance(usernames_field, str):
                        names = [n.strip().lower() for n in usernames_field.replace(";", ",").split(",") if n.strip()]
                    elif isinstance(usernames_field, list):
                        names = [str(n).strip().lower() for n in usernames_field if str(n).strip()]
                    if not names or normalized_history_username in names:
                        filtered_records.append(rec)

                if not filtered_records:
                    st.info("No history rows match this username after filtering mixed-user records.")
                    return
                records = filtered_records

                history_records_sorted = sorted(records, key=_record_season_id, reverse=True)
                history_table_rows = []
                for idx, record in enumerate(history_records_sorted):
                    season_label = record.get("season") or record.get("season_id") or "-"
                    scholar_pct = _record_scholar_pct(record)
                    totals = _aggregated_totals_from_record(record)

                    payout_currency = record.get("payout_currency")
                    scholar_payout_value = record.get("scholar_payout")
                    if scholar_payout_value is not None:
                        sps_price = prices.get("SPS") or prices.get("sps") or 0
                        payout_display = f"{scholar_payout_value:,.2f} SPS (${scholar_payout_value * sps_price:,.2f})"
                    else:
                        payout_display = _format_scholar_payout(
                            str(payout_currency or "SPS"),
                            totals,
                            scholar_pct,
                            prices,
                        )

                    history_table_rows.append(
                        {
                            "Season": season_label,
                            "Ranked tokens": _format_token_amounts_dict(
                                totals.ranked.token_amounts, prices
                            ),
                            "Tournament tokens": _format_token_amounts_dict(
                                totals.tournament.token_amounts, prices
                            ),
                            "Brawl tokens": _format_token_amounts_dict(
                                totals.brawl.token_amounts, prices
                            ),
                            "Overall tokens": _format_token_amounts_dict(
                                totals.overall.token_amounts, prices
                            ),
                            "Scholar payout": payout_display,
                            "Currency": payout_currency,
                        }
                    )

                if history_table_rows:
                    with st.expander("Raw rows (debug)", expanded=False):
                        st.json(history_records_sorted)

                    st.dataframe(
                        history_table_rows,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Ranked tokens": st.column_config.TextColumn(),
                            "Tournament tokens": st.column_config.TextColumn(),
                            "Brawl tokens": st.column_config.TextColumn(),
                            "Overall tokens": st.column_config.TextColumn(),
                        },
                    )

                    st.markdown("#### Update payout currency")
                    for idx, record in enumerate(history_records_sorted[:2]):
                        stored_currency = str(record.get("payout_currency") or "SPS")
                        default_currency = stored_currency if stored_currency in history_currency_options else history_currency_options[0]
                        selection_key = f"history_currency_{normalized_history_username.lower()}_{_record_season_id(record)}_{idx}"
                        cols = st.columns([1.5, 1.5, 2, 1])
                        cols[0].markdown(f"**Season {_record_season_id(record)}**")
                        cols[1].markdown(f"{record.get('season_start') or '-'} → {record.get('season_end') or '-'}")
                        selected_currency = cols[2].selectbox(
                            "Payout currency",
                            options=history_currency_options,
                            key=selection_key,
                            index=history_currency_options.index(default_currency),
                        )
                        save_key = f"history_save_{normalized_history_username.lower()}_{_record_season_id(record)}_{idx}"
                        if cols[3].button("Save currency", key=save_key):
                            if update_season_currency(
                                normalized_history_username, _record_season_id(record), selected_currency
                            ):
                                if feedback_key:
                                    st.session_state[feedback_key] = (
                                        f"Scholar payout currency updated to {selected_currency} for season {_record_season_id(record)}."
                                    )
                                st.experimental_rerun()  # type: ignore[attr-defined]
                            else:
                                cols[3].error("Failed to update the payout currency; check your database configuration.")


def _merge_tournament_records(tournament_lists, season: int) -> list[dict]:
    merged: list[dict] = []
    for tournaments in tournament_lists:
        for tournament in tournaments:
            if tournament.season != season:
                continue
            merged.append(tournament.raw or {})
    return merged


def _aggregate_history_record(record, prices) -> AggregatedTotals:
    ranked = CategoryTotals(
        token_amounts=_parse_token_amounts(record.get("ranked_tokens")),
        usd=_safe_float(record.get("ranked_usd")),
    )
    brawl = CategoryTotals(
        token_amounts=_parse_token_amounts(record.get("brawl_tokens")),
        usd=_safe_float(record.get("brawl_usd")),
    )
    tournament = CategoryTotals(
        token_amounts=_parse_token_amounts(record.get("tournament_tokens")),
        usd=_safe_float(record.get("tournament_usd")),
    )
    entry_fees = CategoryTotals(
        token_amounts=_parse_token_amounts(record.get("entry_fees_tokens")),
        usd=_safe_float(record.get("entry_fees_usd")),
    )
    overall_tokens = _merge_token_amounts(
        ranked.token_amounts, brawl.token_amounts, tournament.token_amounts, entry_fees.token_amounts
    )
    overall_usd = _safe_float(record.get("overall_usd"))
    if not overall_usd:
        overall_usd = _sum_rewards_usd([ranked, brawl, tournament], prices) - entry_fees.usd

    return AggregatedTotals(
        ranked=ranked,
        brawl=brawl,
        tournament=tournament,
        entry_fees=entry_fees,
        overall=CategoryTotals(token_amounts=overall_tokens, usd=overall_usd),
    )


if __name__ == "__main__":
    render_page()
    render_footer()
