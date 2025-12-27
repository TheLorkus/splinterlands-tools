from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable

from dotenv import load_dotenv

from scholar_helper.services.aggregation import aggregate_totals
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments_for_season,
    fetch_unclaimed_balance_history_for_season,
)
from scholar_helper.services.storage import (
    get_supabase_client,
    upsert_season_snapshot_if_better,
    upsert_tournament_logs,
)

logger = logging.getLogger(__name__)


def parse_usernames(raw_args: Iterable[str]) -> list[str]:
    names: list[str] = []
    for entry in raw_args:
        for piece in entry.split(","):
            value = piece.strip()
            if value:
                names.append(value)
    # Preserve order while deduplicating
    seen = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def fetch_rows_for_season(usernames: Iterable[str], season) -> tuple[dict[str, list], dict[str, list]]:
    rewards: dict[str, list] = {}
    tournaments: dict[str, list] = {}
    for username in usernames:
        logger.info("Fetching rewards for %s", username)
        user_rewards = fetch_unclaimed_balance_history_for_season(username, season)
        rewards[username] = user_rewards
        logger.info("Fetching tournaments for %s", username)
        user_tournaments = fetch_tournaments_for_season(username, season)
        tournaments[username] = user_tournaments
    return rewards, tournaments


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch current season totals and sync to the database.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--usernames",
        "-u",
        nargs="+",
        required=True,
        help="Usernames to fetch (comma-separated or multiple flags).",
    )
    parser.add_argument(
        "--scholar-pct",
        "-s",
        type=float,
        default=50.0,
        help="Scholar share percentage saved with each snapshot.",
    )
    parser.add_argument(
        "--currency",
        "-c",
        default="SPS",
        help="Payout currency recorded with the season snapshot.",
    )
    args = parser.parse_args(argv)

    usernames = parse_usernames(args.usernames)
    if not usernames:
        parser.error("At least one username must be provided.")

    logger.info("Usernames: %s", ", ".join(usernames))

    season = fetch_current_season()
    prices = fetch_prices()

    client = get_supabase_client()
    if client is None:
        logger.error("Database access is not configured (missing SUPABASE_URL or key).")
        return 1

    reward_map, tournament_map = fetch_rows_for_season(usernames, season)

    for username in usernames:
        reward_rows = reward_map.get(username, [])
        tournament_rows = tournament_map.get(username, [])
        if not reward_rows and not tournament_rows:
            logger.warning("No rows for %s; skipping.", username)
            continue

        totals = aggregate_totals(season, reward_rows, tournament_rows, prices)
        last_reward_at = max((r.created_date for r in reward_rows), default=None)
        last_tournament_at = max((t.start_date for t in tournament_rows if t.start_date), default=None)

        updated, message = upsert_season_snapshot_if_better(
            season,
            username,
            totals,
            args.scholar_pct,
            args.currency,
            len(reward_rows),
            len(tournament_rows),
            last_reward_at,
            last_tournament_at,
            True,
        )
        if updated:
            logger.info("Snapshot saved: %s", message)
        else:
            logger.info("Snapshot skipped: %s", message)

        logger.info("Upserting tournament logs for %s (%s rows)", username, len(tournament_rows))
        upsert_tournament_logs(tournament_rows, username)

    logger.info("Sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
