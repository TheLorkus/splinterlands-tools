from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable, List, Tuple

from dotenv import load_dotenv

from scholar_helper.models import RewardEntry, TournamentResult
from scholar_helper.services.aggregation import aggregate_totals
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments,
    fetch_unclaimed_balance_history,
)
from scholar_helper.services.storage import (
    get_supabase_client,
    upsert_season_totals,
    upsert_tournament_logs,
)

logger = logging.getLogger(__name__)


def parse_usernames(raw_args: Iterable[str]) -> List[str]:
    names: List[str] = []
    for entry in raw_args:
        for piece in entry.split(","):
            value = piece.strip()
            if value:
                names.append(value)
    # Preserve order while deduplicating
    seen = set()
    deduped: List[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def fetch_rows(usernames: Iterable[str]) -> Tuple[List[RewardEntry], List[TournamentResult]]:
    rewards: List[RewardEntry] = []
    tournaments: List[TournamentResult] = []
    for username in usernames:
        logger.info("Fetching rewards for %s", username)
        rewards.extend(fetch_unclaimed_balance_history(username))
        logger.info("Fetching tournaments for %s", username)
        tournaments.extend(fetch_tournaments(username))
    return rewards, tournaments


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch current season totals and sync to Supabase.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--usernames",
        "-u",
        nargs="+",
        required=True,
        help="Usernames to fetch (comma-separated or multiple flags).",
    )
    args = parser.parse_args(argv)

    usernames = parse_usernames(args.usernames)
    if not usernames:
        parser.error("At least one username must be provided.")

    logger.info("Usernames: %s", ", ".join(usernames))

    season = fetch_current_season()
    prices = fetch_prices()

    reward_rows, tournament_rows = fetch_rows(usernames)
    if not reward_rows and not tournament_rows:
        logger.warning("No rows returned; nothing to sync.")
        return 0

    totals = aggregate_totals(season, reward_rows, tournament_rows, prices)
    usernames_label = ",".join(usernames)

    client = get_supabase_client()
    if client is None:
        logger.error("Supabase is not configured (missing SUPABASE_URL or key).")
        return 1

    logger.info("Upserting season totals for season %s", season.id)
    upsert_season_totals(season, usernames_label, totals)
    logger.info("Upserting tournament logs (%s rows)", len(tournament_rows))
    upsert_tournament_logs(tournament_rows, usernames_label)

    logger.info("Sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
