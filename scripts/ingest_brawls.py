from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scholar_helper.services.brawl_persistence import (  # noqa: E402
    fetch_recent_finished_brawl_records,
    ingest_brawl_ids,
    is_guild_tracked,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest recent brawls into the database.")
    parser.add_argument("--guild-id", required=True, help="Guild ID to ingest.")
    parser.add_argument("--last-n", type=int, default=3, help="Number of recent cycles to ingest.")
    args = parser.parse_args(argv)

    if not is_guild_tracked(args.guild_id):
        print("Warning: guild is not tracked; ingestion may be blocked by policy.", file=sys.stderr)

    records = fetch_recent_finished_brawl_records(args.guild_id, n=args.last_n)
    brawl_ids = [str(row.get("tournament_id")) for row in records if row.get("tournament_id")]
    if not brawl_ids:
        print("No recent brawl IDs found.", file=sys.stderr)
        return 1

    result = ingest_brawl_ids(args.guild_id, brawl_ids, records=records)
    print(f"Ingested {result.get('cycles', 0)} cycles and {result.get('players', 0)} player rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
