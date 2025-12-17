from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List

import streamlit as st

from scholar_helper.models import AggregatedTotals, CategoryTotals, PriceQuotes, RewardEntry, SeasonWindow, TournamentResult
from scholar_helper.services.aggregation import aggregate_totals, filter_tournaments_for_season  # noqa: F401
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments,
    fetch_unclaimed_balance_history,
)
from scholar_helper.services.storage import (  # noqa: F401
    get_last_supabase_error,
    get_supabase_client,
    upsert_season_totals,
    upsert_tournament_logs,
)

try:
    from scholar_helper.services.storage import fetch_season_history
except ImportError:  # pragma: no cover - fallback for older deployments
    def fetch_season_history(username: str):
        return []

try:
    from scholar_helper.services.storage import update_season_currency
except ImportError:  # pragma: no cover - fallback for older deployments
    def update_season_currency(username: str, season_id: int, currency: str) -> bool:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def cached_season() -> SeasonWindow:
    return fetch_current_season()


@st.cache_data(ttl=300, show_spinner=False)
def cached_prices():
    return fetch_prices()


@st.cache_data(ttl=300, show_spinner=False)
def cached_rewards(username: str) -> List[RewardEntry]:
    return fetch_unclaimed_balance_history(username)


@st.cache_data(ttl=300, show_spinner=False)
def cached_tournaments(username: str) -> List[TournamentResult]:
    return fetch_tournaments(username)


def clear_caches():
    cached_season.clear()  # type: ignore[attr-defined]
    cached_prices.clear()  # type: ignore[attr-defined]
    cached_rewards.clear()  # type: ignore[attr-defined]
    cached_tournaments.clear()  # type: ignore[attr-defined]


def parse_usernames(raw: str) -> List[str]:
    return [name.strip() for name in raw.split(",") if name.strip()]


def _format_price(value) -> str:
    """Render price safely even if cached values are non-numeric."""
    try:
        return f"${float(value):.6f}"
    except Exception:
        return str(value)


def _format_token_amounts_dict(token_amounts, prices) -> str:
    if not token_amounts:
        return "-"
    parts = []
    for token, amount in token_amounts.items():
        usd = (prices.get(token) or 0) * amount
        parts.append(f"{amount:g} {token} (${usd:,.2f})")
    return "; ".join(parts)


def _format_rewards_list(rewards: List[RewardEntry] | List[TournamentResult], prices) -> str:
    parts = []
    for reward in rewards:
        token = getattr(reward, "token", None) or getattr(reward, "token", None)
        amount = getattr(reward, "amount", None)
        if token is None or amount is None:
            continue
        usd = (prices.get(token) or 0) * amount
        parts.append(f"{amount:g} {token.upper()} (${usd:,.2f})")
    return "; ".join(parts) if parts else "-"


def _build_currency_options(per_user_totals: List[tuple[str, AggregatedTotals]]) -> List[str]:
    currencies = {"SPS", "USD", "ETH", "HIVE", "BTC", "DEC", "VOUCHER"}
    for _, totals in per_user_totals:
        tokens = totals.overall.token_amounts.keys()
        currencies.update(token.upper() for token in tokens if isinstance(token, str))
    base_order = ["SPS", "USD", "ETH", "HIVE", "BTC", "DEC", "VOUCHER"]
    extras = [token for token in sorted(currencies) if token not in base_order]
    ordered = [token for token in base_order if token in currencies]
    return ordered + extras


def _format_scholar_payout(
    currency: str,
    totals: AggregatedTotals,
    scholar_pct: float,
    prices: PriceQuotes,
    explicit_sps: float | None = None,
) -> str:
    currency_key = currency.upper()
    if explicit_sps is None:
        sps_amount = totals.overall.token_amounts.get("SPS", 0.0) * (scholar_pct / 100)
    else:
        sps_amount = explicit_sps
    sps_price = prices.get("SPS") or prices.get("sps") or 0
    usd_value = sps_amount * sps_price

    if currency_key == "USD":
        return f"${usd_value:,.2f}"
    if sps_amount == 0 or usd_value == 0:
        if currency_key == "SPS":
            return f"{sps_amount:,.2f} SPS (${usd_value:,.2f})"
        return f"0.00 {currency_key}"
    if currency_key == "SPS":
        return f"{sps_amount:,.2f} SPS (${usd_value:,.2f})"

    target_price = prices.get(currency_key) or prices.get(currency_key.lower())
    if not target_price:
        return "-"
    converted = usd_value / target_price if target_price else 0.0
    return f"{converted:,.2f} {currency_key} (${usd_value:,.2f})"


def _safe_float(value: object | None, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _safe_int(value: object | None, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _try_parse_int(value: object | None) -> int | None:
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


def _parse_token_amounts(payload: object | None) -> Dict[str, float]:
    if not payload:
        return {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    tokens: Dict[str, float] = {}
    for token, amount in payload.items():
        try:
            key = str(token).upper()
            tokens[key] = float(amount)
        except Exception:
            continue
    return tokens


def _category_totals_from_record(record: Dict[str, object], prefix: str) -> CategoryTotals:
    tokens = _parse_token_amounts(record.get(f"{prefix}_tokens"))
    usd_value = _safe_float(record.get(f"{prefix}_usd"))
    return CategoryTotals(token_amounts=tokens, usd=usd_value)


def _merge_token_amounts(*parts: Dict[str, float]) -> Dict[str, float]:
    merged: Dict[str, float] = defaultdict(float)
    for part in parts:
        for token, amount in part.items():
            merged[token.upper()] += amount
    return dict(merged)


def _aggregated_totals_from_record(record: Dict[str, object]) -> AggregatedTotals:
    ranked = _category_totals_from_record(record, "ranked")
    brawl = _category_totals_from_record(record, "brawl")
    tournament = _category_totals_from_record(record, "tournament")
    entry_fees = _category_totals_from_record(record, "entry_fees")
    # Overall tokens exclude entry fees for display.
    overall_tokens = _merge_token_amounts(
        ranked.token_amounts,
        brawl.token_amounts,
        tournament.token_amounts,
    )
    overall_usd = _safe_float(record.get("overall_usd"))
    if not overall_usd:
        overall_usd = ranked.usd + brawl.usd + tournament.usd + entry_fees.usd
    overall = CategoryTotals(token_amounts=overall_tokens, usd=overall_usd)
    return AggregatedTotals(
        ranked=ranked,
        brawl=brawl,
        tournament=tournament,
        entry_fees=entry_fees,
        overall=overall,
    )


def _record_scholar_pct(record: Dict[str, object]) -> float:
    return _safe_float(record.get("scholar_pct"))


def _record_season_id(record: Dict[str, object]) -> int:
    return _safe_int(record.get("season_id"))


def _sum_rewards_sps(rewards) -> float:
    return sum(r.amount for r in rewards if getattr(r, "token", "").upper() == "SPS")


def _sum_rewards_usd(rewards, prices) -> float:
    total = 0.0
    for r in rewards:
        # Handle RewardEntry / TokenAmount objects.
        token = getattr(r, "token", None)
        amount = getattr(r, "amount", None)
        if token is not None and amount is not None:
            price = prices.get(token) or prices.get(str(token).lower()) or 0
            total += amount * price
            continue

        # Handle Aggregated/Category totals with token_amounts dict.
        token_amounts = getattr(r, "token_amounts", None)
        if isinstance(token_amounts, dict):
            for tok, amt in token_amounts.items():
                price = prices.get(tok) or prices.get(str(tok).lower()) or 0
                total += amt * price
            continue

        # Handle TournamentResult objects with rewards list.
        rewards_list = getattr(r, "rewards", None)
        if isinstance(rewards_list, list):
            for reward in rewards_list:
                token_inner = getattr(reward, "token", None)
                amount_inner = getattr(reward, "amount", None)
                if token_inner is None or amount_inner is None:
                    continue
                price = prices.get(token_inner) or prices.get(str(token_inner).lower()) or 0
                total += amount_inner * price
    return total


def _get_finish_for_tournament(t: TournamentResult, username: str) -> str | int:
    if t.finish is not None:
        return t.finish
    detail = t.raw.get("detail") if isinstance(t.raw, dict) else None
    target = username.lower()
    players = detail.get("players") if isinstance(detail, dict) else None
    if isinstance(players, list):
        for p in players:
            if not isinstance(p, dict):
                continue
            if str(p.get("player", "")).lower() == target:
                finish_value = _try_parse_int(p.get("finish"))
                if finish_value is not None:
                    return finish_value
                break
    current_player = detail.get("current_player") if isinstance(detail, dict) else None
    if isinstance(current_player, dict) and str(current_player.get("player", "")).lower() == target:
        finish_value = _try_parse_int(current_player.get("finish"))
        if finish_value is not None:
            return finish_value
    return "-"


def _render_user_summary(username: str, totals: AggregatedTotals, scholar_pct: float) -> None:
    st.markdown(
        f"<div style='font-size:16px; font-weight:600; font-family:inherit;'>{username}</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Overall", f"${totals.overall.usd:,.2f}")
    cols[1].metric("Ranked", f"${totals.ranked.usd:,.2f}")
    cols[2].metric("Brawl", f"${totals.brawl.usd:,.2f}")
    cols[3].metric("Tournament", f"${totals.tournament.usd:,.2f}")
