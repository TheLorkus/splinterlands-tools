from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from cachetools import TTLCache, cached

from scholar_helper.models import (
    HostedTournament,
    PriceQuotes,
    RewardEntry,
    SeasonWindow,
    TokenAmount,
    TournamentResult,
)

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0

_client = httpx.Client(timeout=HTTP_TIMEOUT)
_settings_cache = TTLCache(maxsize=16, ttl=300)
_prices_cache = TTLCache(maxsize=16, ttl=300)
_hosted_tournaments_cache = TTLCache(maxsize=64, ttl=300)


@cached(_settings_cache)
def fetch_settings() -> dict[str, object]:
    resp = _client.get("https://api.splinterlands.com/settings")
    resp.raise_for_status()
    return resp.json()


def fetch_current_season() -> SeasonWindow:
    settings: dict[str, object] | None = None
    season_id: int | str | None = None

    try:
        settings = fetch_settings()
        season_payload_raw = settings.get("season") if isinstance(settings, dict) else None
        season_payload: dict[str, object] = season_payload_raw if isinstance(season_payload_raw, dict) else {}
        season_id_raw = season_payload.get("id")
        if isinstance(season_id_raw, int | str):
            season_id = season_id_raw
    except Exception:
        # Best-effort; will fall back to the season endpoint directly
        pass

    season = _fetch_season_from_api(season_id)
    if season:
        return season

    if settings:
        season_payload_raw = settings.get("season") if isinstance(settings, dict) else None
        previous_raw = settings.get("previous_season") if isinstance(settings, dict) else None
        season_payload = season_payload_raw if isinstance(season_payload_raw, dict) else {}
        previous = previous_raw if isinstance(previous_raw, dict) else None
        return SeasonWindow.from_settings(season_payload, previous)

    raise RuntimeError("Unable to fetch season data from Splinterlands API")


@cached(_hosted_tournaments_cache)
def fetch_hosted_tournaments(username: str) -> list[HostedTournament]:
    url = f"https://api.splinterlands.com/tournaments/mine?username={username}"
    resp = _client.get(url)
    resp.raise_for_status()
    data = resp.json() or []

    hosted: list[HostedTournament] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        start_dt = _parse_dt(raw.get("start_date"))
        allowed_cards = {}
        payouts = []
        data_payload = raw.get("data")
        if isinstance(data_payload, dict):
            allowed_cards = data_payload.get("allowed_cards") or {}
            if not isinstance(allowed_cards, dict):
                allowed_cards = {}
            prizes_payload = data_payload.get("prizes")
            if isinstance(prizes_payload, dict):
                payouts = prizes_payload.get("payouts") or []
                if not isinstance(payouts, list):
                    payouts = []
        hosted.append(
            HostedTournament(
                id=str(raw.get("id")),
                name=str(raw.get("name", "Tournament")),
                start_date=start_dt,
                allowed_cards=allowed_cards,
                payouts=payouts,
                raw=raw,
            )
        )

    hosted.sort(
        key=lambda t: t.start_date if t.start_date else datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return hosted


def fetch_tournament_leaderboard(tournament_id: str, username: str, payouts: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Return player finishes and prize info for a tournament id."""
    detail = _fetch_tournament_detail(tournament_id, username)
    players = detail.get("players") if isinstance(detail, dict) else None
    payouts = payouts or []
    leaderboard: list[dict[str, object]] = []
    if not isinstance(players, list):
        return leaderboard

    for player in players:
        if not isinstance(player, dict):
            continue
        finish_int = _coerce_int(player.get("finish"))
        prize_payload = player.get("ext_prize_info") or player.get("prizes") or player.get("prize") or player.get("player_prize")
        prize_tokens = _parse_prize_payload(prize_payload)
        prize_texts: list[str] = []
        if prize_tokens:
            prize_texts.append(", ".join(f"{t.amount:g} {t.token}" for t in prize_tokens))
        inferred = _infer_prizes_from_payouts(payouts, finish_int)
        if inferred:
            prize_texts.extend(inferred)
        if not prize_texts and prize_payload:
            prize_texts.append(str(prize_payload))
        leaderboard.append(
            {
                "player": player.get("player"),
                "finish": finish_int,
                "prize": "; ".join(prize_texts),
            }
        )

    leaderboard.sort(key=_leaderboard_finish_sort_key)
    return leaderboard


def _leaderboard_finish_sort_key(row: dict[str, object]) -> int:
    finish_val = row.get("finish")
    finish_int = _coerce_int(finish_val)
    return finish_int if finish_int is not None else 1_000_000


def _infer_prizes_from_payouts(payouts: list[dict[str, object]], finish: int | None) -> list[str]:
    if not finish or finish <= 0:
        return []
    prizes: list[str] = []
    for payout in payouts:
        if not isinstance(payout, dict):
            continue
        start_place = payout.get("start_place")
        end_place = payout.get("end_place")
        start_int = _coerce_int(start_place)
        end_int = _coerce_int(end_place)
        if start_int is None or end_int is None:
            continue
        if not (start_int <= finish <= end_int):
            continue
        items_raw = payout.get("items")
        items = items_raw if isinstance(items_raw, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            qty = _coerce_float(item.get("qty") or item.get("amount") or item.get("value"))
            token = item.get("type") or item.get("token")
            text = item.get("text")
            usd_value = item.get("usd_value")
            label = ""
            if token == "CUSTOM":
                label = f"{qty:g}x {text}" if qty is not None and text else text or "Custom prize"
                usd_val = _coerce_float(usd_value)
                if usd_val is not None:
                    label += f" (~${usd_val:g})"
            elif qty is not None and token:
                label = f"{qty:g} {token}"
            if label:
                prizes.append(label)
    return prizes


def fetch_tournaments(username: str, limit: int | None = 200) -> list[TournamentResult]:
    url = f"https://api.splinterlands.com/tournaments/completed?username={username}"
    resp = _client.get(url)
    resp.raise_for_status()
    data = resp.json() or []

    results: list[TournamentResult] = []
    future_cutoff = datetime.now(UTC) + timedelta(days=1)
    filtered: list[dict[str, object]] = []
    for raw in data:
        if isinstance(raw, dict):
            filtered.append(raw)

    # Sort newest-first so the limit keeps the most recent events.
    filtered.sort(key=_list_payload_sort_key, reverse=True)
    if limit and limit > 0:
        filtered = filtered[:limit]

    for raw in filtered:
        entry_fee = _parse_entry_fee(raw.get("entry_fee"))
        start_dt = _parse_dt(raw.get("start_date"))
        if start_dt and start_dt > future_cutoff:
            continue

        detail = _fetch_tournament_detail(raw.get("id"), username)
        finish = _extract_player_finish(detail, username)
        # Prefer detail payload for dates/entry_fee if present.
        if isinstance(detail, dict):
            entry_fee = _parse_entry_fee(detail.get("entry_fee")) or entry_fee
            start_dt = _parse_dt(detail.get("start_date")) if detail.get("start_date") else start_dt

        rewards = _extract_rewards_for_player(detail, username)
        if not rewards:
            rewards = _parse_player_rewards(raw)

        combined_raw: dict[str, object] = {"list": raw}
        if detail:
            combined_raw["detail"] = detail

        results.append(
            TournamentResult(
                id=str(raw.get("id")),
                name=str(raw.get("name", "Tournament")),
                start_date=start_dt,
                entry_fee=entry_fee,
                username=username,
                rewards=rewards,
                finish=finish,
                raw=combined_raw,
            )
        )

    # Ensure newest-first ordering in the return payload.
    results.sort(key=_tournament_sort_key, reverse=True)
    return results


def fetch_tournaments_for_season(username: str, season: SeasonWindow, limit: int | None = 1000) -> list[TournamentResult]:
    """
    Fetch tournaments for a user with enough coverage to span the season window.

    Uses a higher limit and stops once tournaments fall before the season start.
    """
    params: dict[str, str] = {"username": username}
    if limit:
        params["limit"] = str(limit)
    resp = _client.get("https://api.splinterlands.com/tournaments/completed", params=params)
    resp.raise_for_status()
    data = resp.json() or []

    results: list[TournamentResult] = []
    future_cutoff = datetime.now(UTC) + timedelta(days=1)
    filtered: list[dict[str, object]] = []
    for raw in data:
        if isinstance(raw, dict):
            filtered.append(raw)

    filtered.sort(key=_list_payload_sort_key, reverse=True)

    for raw in filtered:
        entry_fee = _parse_entry_fee(raw.get("entry_fee"))
        start_dt = _parse_dt(raw.get("start_date"))
        if start_dt and start_dt > future_cutoff:
            continue

        detail = _fetch_tournament_detail(raw.get("id"), username)
        finish = _extract_player_finish(detail, username)
        if isinstance(detail, dict):
            entry_fee = _parse_entry_fee(detail.get("entry_fee")) or entry_fee
            start_dt = _parse_dt(detail.get("start_date")) if detail.get("start_date") else start_dt

        rewards = _extract_rewards_for_player(detail, username)
        if not rewards:
            rewards = _parse_player_rewards(raw)

        combined_raw: dict[str, object] = {"list": raw}
        if detail:
            combined_raw["detail"] = detail

        result = TournamentResult(
            id=str(raw.get("id")),
            name=str(raw.get("name", "Tournament")),
            start_date=start_dt,
            entry_fee=entry_fee,
            username=username,
            rewards=rewards,
            finish=finish,
            raw=combined_raw,
        )

        if result.start_date:
            if result.start_date < season.starts:
                break
            if result.start_date > season.ends:
                continue

        results.append(result)

    results.sort(key=_tournament_sort_key, reverse=True)
    return results


def fetch_unclaimed_balance_history(username: str, token_type: str = "SPS", offset: int = 0, limit: int = 1000) -> list[RewardEntry]:
    url = f"https://api.splinterlands.com/players/unclaimed_balance_history?username={username}&token_type={token_type}&offset={offset}&limit={limit}"
    resp = _client.get(url)
    resp.raise_for_status()
    payload = resp.json() or []

    entries: list[RewardEntry] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        created_at = _parse_dt(raw.get("created_date"))
        amount = _coerce_float(raw.get("amount", 0) or 0)
        if amount is None or amount <= 0:
            # Skip zero/negative adjustments so totals don't go negative
            continue
        entries.append(
            RewardEntry(
                id=str(raw.get("id")),
                player=str(raw.get("player", username)),
                token=str(raw.get("token", token_type)),
                amount=float(amount),
                type=str(raw.get("type", "")),
                created_date=created_at,
                username=username,
                raw=raw,
            )
        )
    return entries


def fetch_unclaimed_balance_history_for_season(
    username: str,
    season: SeasonWindow,
    token_type: str = "SPS",
    page_limit: int = 500,
) -> list[RewardEntry]:
    """
    Fetch rewards with pagination until we cover the season window.

    Stops when the oldest fetched reward is older than the season start (or no rows returned).
    Filters results to rewards within the season window and skips zero/negative adjustments.
    """
    offset = 0
    entries: list[RewardEntry] = []
    while True:
        url = f"https://api.splinterlands.com/players/unclaimed_balance_history?username={username}&token_type={token_type}&offset={offset}&limit={page_limit}"
        resp = _client.get(url)
        resp.raise_for_status()
        payload = resp.json() or []
        if not isinstance(payload, list) or not payload:
            break

        oldest_in_page: datetime | None = None
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            created_at = _parse_dt(raw.get("created_date"))
            if oldest_in_page is None or created_at < oldest_in_page:
                oldest_in_page = created_at
            amount = _coerce_float(raw.get("amount", 0) or 0)
            if amount is None or amount <= 0:
                continue
            if created_at < season.starts or created_at > season.ends:
                continue
            entries.append(
                RewardEntry(
                    id=str(raw.get("id")),
                    player=str(raw.get("player", username)),
                    token=str(raw.get("token", token_type)),
                    amount=float(amount),
                    type=str(raw.get("type", "")),
                    created_date=created_at,
                    username=username,
                    raw=raw,
                )
            )

        # If we reached before the season starts or got a short page, stop.
        if oldest_in_page and oldest_in_page < season.starts:
            break
        if len(payload) < page_limit:
            break
        offset += page_limit

    entries.sort(key=lambda r: r.created_date, reverse=True)
    return entries


@cached(_prices_cache)
def fetch_prices() -> PriceQuotes:
    resp = _client.get("https://prices.splinterlands.com/prices")
    resp.raise_for_status()
    data = resp.json() or {}
    prices: dict[str, float] = {}
    for key, value in data.items():
        extracted = _extract_price(value)
        if extracted is None:
            continue
        token_key = str(key).lower()
        sanitized = _sanitize_price(token_key, extracted)
        if sanitized is None:
            continue
        prices[token_key] = sanitized
    return PriceQuotes(token_to_usd=prices)


def _parse_entry_fee(value: object) -> TokenAmount | None:
    if not value:
        return None
    # API shape is e.g., "400 DEC" or "2 SPS"
    if isinstance(value, str):
        parts = value.split()
        if len(parts) == 2:
            amount = _coerce_float(parts[0])
            token = parts[1]
            if amount is not None:
                return TokenAmount(token=token, amount=amount)
    return None


def _parse_player_rewards(raw: dict[str, object]) -> list[TokenAmount]:
    rewards: list[TokenAmount] = []
    # Some tournaments may include `player_prizes` or `player_prize` entries
    prize_payload = None
    for key in ["player_prizes", "player_prize", "prize", "prizes"]:
        if key in raw:
            prize_payload = raw[key]
            break

    if isinstance(prize_payload, list):
        for entry in prize_payload:
            if not isinstance(entry, dict):
                continue
            qty = _coerce_float(entry.get("qty") or entry.get("amount") or entry.get("value"))
            token = entry.get("type") or entry.get("token")
            if qty is not None and token:
                rewards.append(TokenAmount(token=str(token), amount=qty))
    elif isinstance(prize_payload, dict):
        qty = _coerce_float(prize_payload.get("qty") or prize_payload.get("amount") or prize_payload.get("value"))
        token = prize_payload.get("type") or prize_payload.get("token")
        if qty is not None and token:
            rewards.append(TokenAmount(token=str(token), amount=qty))

    return rewards


def _parse_prize_payload(payload: object) -> list[TokenAmount]:
    rewards: list[TokenAmount] = []
    if not payload:
        return rewards

    parsed: object = payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except Exception:
            return rewards

    if isinstance(parsed, list):
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            qty = _coerce_float(entry.get("qty") or entry.get("amount") or entry.get("value"))
            token = entry.get("type") or entry.get("token")
            if qty is not None and token:
                rewards.append(TokenAmount(token=str(token), amount=qty))
    elif isinstance(parsed, dict):
        qty = _coerce_float(parsed.get("qty") or parsed.get("amount") or parsed.get("value"))
        token = parsed.get("type") or parsed.get("token")
        if qty is not None and token:
            rewards.append(TokenAmount(token=str(token), amount=qty))

    return rewards


def _parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            logger.debug("Failed to parse datetime from %s", value, exc_info=True)
    return datetime.now(tz=UTC)


def _coerce_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: object | None) -> int | None:
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


def _is_number(value: object | None) -> bool:
    return _coerce_float(value) is not None


def _extract_price(value: object) -> float | None:
    """Convert price payloads to a float, handling numeric and dict shapes."""
    price_val = _coerce_float(value)
    if price_val is not None:
        return price_val if price_val > 0 else None
    if isinstance(value, dict):
        for candidate in (
            value.get("usd"),
            value.get("USD"),
            value.get("price"),
            value.get("last"),
            value.get("close"),
        ):
            candidate_val = _coerce_float(candidate)
            if candidate_val is not None:
                return candidate_val if candidate_val > 0 else None
    return None


def _sanitize_price(token: str, price: float) -> float | None:
    """Drop clearly bad prices for low-priced tokens to avoid runaway USD totals."""
    ceilings = {
        "sps": 1.0,
        "dec": 0.01,
        "voucher": 2.0,
        "glx": 1.0,
        "glusd": 10.0,
        "hive": 10.0,
        "hbd": 10.0,
    }
    cap = ceilings.get(token.lower())
    if cap is not None and price > cap:
        return None
    return price


def _fetch_tournament_detail(tournament_id: object, username: str) -> dict[str, object] | None:
    if not tournament_id:
        return None
    try:
        url = "https://api.splinterlands.com/tournaments/find"
        resp = _client.get(url, params={"id": str(tournament_id), "username": username})
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            return payload
    except Exception:
        logger.debug("Failed to fetch tournament detail for %s", tournament_id, exc_info=True)
    return None


def _extract_rewards_for_player(detail_payload: dict[str, object] | None, username: str) -> list[TokenAmount]:
    """Pull prize tokens for the requested player from a tournament detail payload."""
    if not detail_payload:
        return []

    target = username.lower()

    players = detail_payload.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            if str(player.get("player", "")).lower() != target:
                continue
            rewards = _parse_prize_payload(player.get("ext_prize_info") or player.get("prize") or player.get("prizes") or player.get("player_prize"))
            if rewards:
                return rewards

    current_player = detail_payload.get("current_player")
    if isinstance(current_player, dict) and str(current_player.get("player", "")).lower() == target:
        rewards = _parse_prize_payload(current_player.get("ext_prize_info") or current_player.get("prize") or current_player.get("prizes") or current_player.get("player_prize"))
        if rewards:
            return rewards

    return []


def _tournament_sort_key(result: TournamentResult) -> datetime:
    if result.start_date:
        return result.start_date
    return datetime.min.replace(tzinfo=UTC)


def _list_payload_sort_key(raw: dict[str, object]) -> datetime:
    start_dt = _parse_dt(raw.get("start_date"))
    return start_dt if start_dt else datetime.min.replace(tzinfo=UTC)


def _extract_player_finish(detail_payload: dict[str, object] | None, username: str) -> int | None:
    if not detail_payload:
        return None
    target = username.lower()

    players = detail_payload.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            if str(player.get("player", "")).lower() != target:
                continue
            finish_val = _coerce_int(player.get("finish"))
            if finish_val is not None:
                return finish_val

    current_player = detail_payload.get("current_player")
    if isinstance(current_player, dict) and str(current_player.get("player", "")).lower() == target:
        finish_val = _coerce_int(current_player.get("finish"))
        if finish_val is not None:
            return finish_val

    return None


def _fetch_season_from_api(season_id: int | str | None) -> SeasonWindow | None:
    """Fetch the current season from the /season endpoint, deriving start conservatively."""
    params: dict[str, str] = {}
    if season_id is not None:
        params["id"] = str(season_id)
    try:
        resp = _client.get("https://api.splinterlands.com/season", params=params or None)
        resp.raise_for_status()
        data = resp.json() or {}
        if not isinstance(data, dict):
            return None
        resolved_id = _coerce_int(data.get("id") or season_id or 0) or 0
        ends = _parse_dt(data.get("ends"))
        starts = ends - timedelta(days=15)
        return SeasonWindow(id=resolved_id, ends=ends, starts=starts)
    except Exception:
        return None


# Lightweight public wrappers for ingestion and scripting use-cases.
def fetch_tournament_detail_raw(tournament_id: object, username: str) -> dict[str, object] | None:
    """Return the raw /tournaments/find payload for a given tournament id."""
    return _fetch_tournament_detail(tournament_id, username)


def parse_prize_payload(payload: object) -> list[TokenAmount]:
    """Expose prize parsing for ingestion scripts."""
    return _parse_prize_payload(payload)


def infer_prizes_from_payouts(payouts: list[dict[str, object]], finish: int | None) -> list[str]:
    """Expose prize inference from payout ranges for ingestion scripts."""
    return _infer_prizes_from_payouts(payouts, finish)


def parse_entry_fee(value: object) -> TokenAmount | None:
    """Expose entry fee parsing for ingestion scripts."""
    return _parse_entry_fee(value)


def parse_datetime(value: object) -> datetime:
    """Expose datetime parsing for ingestion scripts."""
    return _parse_dt(value)
