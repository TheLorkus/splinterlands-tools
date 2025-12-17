from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


@dataclass
class SeasonWindow:
    id: int
    ends: datetime
    starts: datetime

    @classmethod
    def from_api(cls, payload: Dict[str, object]) -> "SeasonWindow":
        """Build a SeasonWindow from the season endpoint payload."""
        season_id = int(payload.get("id", 0))
        ends_raw = payload.get("ends")
        ends = _parse_timestamp(ends_raw)
        # Splinterlands seasons are 15 days; derive start conservatively if not provided.
        starts = ends - timedelta(days=15)
        return cls(id=season_id, ends=ends, starts=starts)

    @classmethod
    def from_settings(cls, current: Dict[str, object], previous: Optional[Dict[str, object]]) -> "SeasonWindow":
        """Build a SeasonWindow using current + previous season info from /settings."""
        season_id = int(current.get("id", 0))
        ends = _parse_timestamp(current.get("ends"))
        prev_end = _parse_timestamp(previous.get("ends")) if previous else None
        starts = prev_end or (ends - timedelta(days=15))
        return cls(id=season_id, ends=ends, starts=starts)


@dataclass
class TokenAmount:
    token: str
    amount: float


@dataclass
class TournamentResult:
    id: str
    name: str
    start_date: Optional[datetime]
    entry_fee: Optional[TokenAmount]
    rewards: List[TokenAmount] = field(default_factory=list)
    finish: Optional[int] = None
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class HostedTournament:
    id: str
    name: str
    start_date: Optional[datetime]
    allowed_cards: Dict[str, object] = field(default_factory=dict)
    payouts: List[Dict[str, object]] = field(default_factory=list)
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class RewardEntry:
    id: str
    player: str
    token: str
    amount: float
    type: str
    created_date: datetime
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class PriceQuotes:
    token_to_usd: Dict[str, float]

    def get(self, token: str) -> Optional[float]:
        return self.token_to_usd.get(token.lower()) or self.token_to_usd.get(token.upper())


@dataclass
class CategoryTotals:
    token_amounts: Dict[str, float] = field(default_factory=dict)
    usd: float = 0.0


@dataclass
class AggregatedTotals:
    ranked: CategoryTotals
    brawl: CategoryTotals
    tournament: CategoryTotals
    entry_fees: CategoryTotals
    overall: CategoryTotals


def _parse_timestamp(value: object) -> datetime:
    """Parse an ISO-8601 timestamp string into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(tz=timezone.utc)
