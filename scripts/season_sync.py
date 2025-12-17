from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from scholar_helper.services.aggregation import aggregate_totals
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments,
    fetch_unclaimed_balance_history,
)
from scholar_helper.services.storage import upsert_season_totals, upsert_tournament_logs


def _parse_usernames(value: str | None) -> list[str]:
    if not value:
        return []
    return [name.strip() for name in value.split(",") if name.strip()]


def _wait_until(target: datetime) -> None:
    seconds = (target - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return
    logging.info("Sleeping for %.1f minutes until %s", seconds / 60, target.isoformat())
    time.sleep(seconds)


def _sync_for_season(
    season,
    usernames: list[str],
    scholar_pct: float,
    payout_currency: str,
) -> None:
    if not usernames:
        logging.warning("No usernames configured for sync.")
        return
    try:
        prices = fetch_prices()
    except Exception as exc:
        logging.exception("Unable to fetch prices: %s", exc)
        return

    for username in usernames:
        logging.info("Syncing %s for season %s", username, season.id)
        try:
            rewards = fetch_unclaimed_balance_history(username)
            tournaments = fetch_tournaments(username)
            totals = aggregate_totals(season, rewards, tournaments, prices)
            upsert_season_totals(season, username, totals, scholar_pct, payout_currency)
            upsert_tournament_logs(tournaments, username)
            logging.info("Successfully synced %s", username)
        except Exception as exc:
            logging.exception("Failed to sync %s: %s", username, exc)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sync season totals to Supabase before season boundary.")
    parser.add_argument(
        "--usernames",
        "-u",
        help="Comma-separated usernames to sync (falls back to SYNC_USERNAMES env var).",
    )
    parser.add_argument(
        "--scholar-pct",
        "-s",
        type=float,
        default=float(os.getenv("SYNC_SCHOLAR_PCT", "50")),
        help="Scholar share percentage saved with each delta.",
    )
    parser.add_argument(
        "--currency",
        "-c",
        default=os.getenv("SYNC_PAYOUT_CURRENCY", "SPS"),
        help="Payout currency recorded with the season snapshot.",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run immediately once and exit (no long sleep until season end).",
    )
    args = parser.parse_args()

    usernames = _parse_usernames(args.usernames) or _parse_usernames(os.getenv("SYNC_USERNAMES"))
    if not usernames:
        logging.error("No usernames configured via CLI or SYNC_USERNAMES.")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    logging.info("Starting seasonal sync%s for users: %s", " (run-now)" if args.run_now else " daemon", ", ".join(usernames))

    if args.run_now:
        season = fetch_current_season()
        _sync_for_season(season, usernames, args.scholar_pct, args.currency)
        return

    while True:
        try:
            season = fetch_current_season()
            target = season.ends - timedelta(minutes=10)
            if target <= datetime.now(timezone.utc):
                logging.warning("Season already within 10 minutes; syncing immediately.")
            else:
                _wait_until(target)

            season = fetch_current_season()
            _sync_for_season(season, usernames, args.scholar_pct, args.currency)

            buffer_until = season.ends + timedelta(minutes=1)
            seconds = max((buffer_until - datetime.now(timezone.utc)).total_seconds(), 60)
            logging.info("Season %s synced; sleeping %.1f minutes until next season", season.id, seconds / 60)
            time.sleep(seconds)
        except KeyboardInterrupt:
            logging.info("Stopping seasonal sync daemon.")
            break
        except Exception as exc:
            logging.exception("Unexpected error in sync daemon: %s", exc)
            time.sleep(300)


if __name__ == "__main__":
    main()
