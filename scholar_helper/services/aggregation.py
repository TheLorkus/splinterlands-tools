from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from scholar_helper.models import (
    AggregatedTotals,
    CategoryTotals,
    PriceQuotes,
    RewardEntry,
    SeasonWindow,
    TokenAmount,
    TournamentResult,
)

RANKED_TYPES = {"modern", "wild", "survival"}
BRAWL_TYPES = {"brawl"}


def filter_rewards_for_season(rewards: Iterable[RewardEntry], season: SeasonWindow) -> List[RewardEntry]:
    return [
        reward
        for reward in rewards
        if season.starts <= reward.created_date <= season.ends  # type: ignore[operator]
    ]


def filter_tournaments_for_season(
    tournaments: Iterable[TournamentResult], season: SeasonWindow
) -> List[TournamentResult]:
    filtered: List[TournamentResult] = []
    for t in tournaments:
        if t.start_date is None:
            filtered.append(t)
            continue
        if season.starts <= t.start_date <= season.ends:  # type: ignore[operator]
            filtered.append(t)
    return filtered


def aggregate_totals(
    season: SeasonWindow,
    rewards: Iterable[RewardEntry],
    tournaments: Iterable[TournamentResult],
    prices: PriceQuotes,
) -> AggregatedTotals:
    rewards_list = filter_rewards_for_season(rewards, season)
    tournaments_list = filter_tournaments_for_season(tournaments, season)

    ranked_entries = [r for r in rewards_list if r.type.lower() in RANKED_TYPES]
    brawl_entries = [r for r in rewards_list if r.type.lower() in BRAWL_TYPES]

    tournament_reward_tokens: List[TokenAmount] = []
    entry_fees: List[TokenAmount] = []
    for t in tournaments_list:
        tournament_reward_tokens.extend(t.rewards)
        if t.entry_fee:
            entry_fees.append(t.entry_fee)

    ranked_totals = _sum_token_amounts(ranked_entries, prices, lambda r: (r.token, r.amount))
    brawl_totals = _sum_token_amounts(brawl_entries, prices, lambda r: (r.token, r.amount))
    tournament_totals = _sum_token_amounts(tournament_reward_tokens, prices, lambda t: (t.token, t.amount))
    entry_fee_totals = _sum_token_amounts(entry_fees, prices, lambda f: (f.token, f.amount))

    overall_tokens: Dict[str, float] = defaultdict(float)
    for bucket in (ranked_totals, brawl_totals, tournament_totals):
        for token, amount in bucket.token_amounts.items():
            overall_tokens[token] += amount

    overall_usd = sum(
        (prices.get(token) or 0) * amount for token, amount in overall_tokens.items()
    )
    overall_totals = CategoryTotals(token_amounts=dict(overall_tokens), usd=overall_usd)

    return AggregatedTotals(
        ranked=ranked_totals,
        brawl=brawl_totals,
        tournament=tournament_totals,
        entry_fees=entry_fee_totals,
        overall=overall_totals,
    )


def _sum_token_amounts(items, prices: PriceQuotes, extractor) -> CategoryTotals:
    token_amounts: Dict[str, float] = defaultdict(float)
    usd_total = 0.0
    for item in items:
        token, amount = extractor(item)
        token_key = str(token).upper()
        token_amounts[token_key] += float(amount)
    for token, amount in token_amounts.items():
        price_raw = prices.get(token) or prices.get(token.lower()) or 0.0
        price = _coerce_price(price_raw) or 0.0
        usd_total += amount * price
    return CategoryTotals(token_amounts=dict(token_amounts), usd=usd_total)


def _coerce_price(value: object) -> float | None:
    """Convert price payloads to a float, tolerating cached dicts from older runs."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for candidate in (
            value.get("usd"),
            value.get("USD"),
            value.get("price"),
            value.get("last"),
            value.get("close"),
        ):
            if isinstance(candidate, (int, float)):
                return float(candidate)
        for candidate in value.values():
            if isinstance(candidate, (int, float)):
                return float(candidate)
    return None
