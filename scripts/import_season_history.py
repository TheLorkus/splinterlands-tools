"""CSV-backed helper that upserts historical rows into the public.season_rewards table."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Sequence, Tuple

import requests
from dotenv import load_dotenv

DEFAULT_SEASON_API = "https://api.splinterlands.com/season?id={season_id}"
_SEASON_WINDOW_CACHE: Dict[int, Tuple[str, str]] = {}

TABLE_NAME = "season_rewards"
TOKEN_COLUMNS = ("ranked_tokens", "brawl_tokens", "tournament_tokens", "entry_fees_tokens")
NUMERIC_COLUMNS = {
    "season_id",
    "ranked_usd",
    "brawl_usd",
    "tournament_usd",
    "entry_fees_usd",
    "overall_usd",
    "scholar_payout",
    "scholar_pct",
}


def _parse_mapping(pairs: Iterable[str]) -> Dict[str, List[str]]:
    """Convert CLI `field=csv_header` arguments into a lookup table."""
    mapping: Dict[str, List[str]] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError("Mappings must be `field=csv column` pairs.")
        field, column = pair.split("=", 1)
        names: List[str] = [name.strip() for name in column.split("+") if name.strip()]
        if not names:
            raise ValueError("Each mapping must include at least one CSV column.")
        mapping[field.strip()] = names
    return mapping


def _coerce_value(field: str, value: str, default_token: str) -> Any:
    if field in TOKEN_COLUMNS:
        return _parse_token_bucket(value, default_token)
    if field == "season_id":
        return int(value)
    if field in NUMERIC_COLUMNS:
        return float(value)
    return value


def _parse_token_bucket(value: str, default_token: str) -> Any:
    """Accept JSON or a numeric value and turn it into a token -> amount dict."""
    text = value.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    try:
        numeric = float(text)
    except ValueError:
        return {default_token: text}
    return {default_token: numeric}


def _ensure_season_window(season_id: int, template: str) -> Tuple[str | None, str | None]:
    if season_id in _SEASON_WINDOW_CACHE:
        return _SEASON_WINDOW_CACHE[season_id]
    url = template.format(season_id=season_id)
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        payload = resp.json() or {}
        season_node = payload.get("season")
        season_data = season_node if isinstance(season_node, dict) else payload if isinstance(payload, dict) else {}
        season_start = (
            payload.get("season_start")
            or payload.get("start")
            or season_data.get("starts")  # type: ignore[attr-defined]
            or season_data.get("start")  # type: ignore[attr-defined]
        )
        season_end = (
            payload.get("season_end")
            or payload.get("end")
            or payload.get("ends")
            or season_data.get("ends")  # type: ignore[attr-defined]
            or season_data.get("end")  # type: ignore[attr-defined]
        )
        if season_start and season_end:
            season_start_str = str(season_start)
            season_end_str = str(season_end)
            _SEASON_WINDOW_CACHE[season_id] = (season_start_str, season_end_str)
            return season_start_str, season_end_str
        print(f"Warning: unable to derive full season window for season {season_id}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - network/logging
        print(f"Warning: failed to fetch season window for {season_id}: {exc}", file=sys.stderr)
    return None, None


def _chunked(sequence: List[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    for i in range(0, len(sequence), size):
        yield sequence[i : i + size]


def _merge_token_values(existing: Any, addition: Any) -> Any:
    if existing is None:
        return addition
    if addition is None:
        return existing
    if isinstance(existing, dict) and isinstance(addition, dict):
        merged = dict(existing)
        for token, amount in addition.items():
            merged[token] = merged.get(token, 0) + amount
        return merged
    if isinstance(existing, (int, float)) and isinstance(addition, (int, float)):
        return existing + addition
    return addition


def _build_payload(
    row: Mapping[str, str],
    column_map: Mapping[str, Sequence[str]],
    default_token: str,
    default_username: str,
    season_api_template: str,
    fetch_season_window: bool,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    username_headers = column_map.get("username", ("username",))
    row_username = ""
    for header in username_headers:
        row_username = (row.get(header) or "").strip()
        if row_username:
            break
    payload["username"] = row_username or default_username
    for column in (
        "season_id",
        "season_start",
        "season_end",
        "ranked_tokens",
        "brawl_tokens",
        "tournament_tokens",
        "entry_fees_tokens",
        "ranked_usd",
        "brawl_usd",
        "tournament_usd",
        "entry_fees_usd",
        "overall_usd",
        "scholar_payout",
        "scholar_pct",
        "payout_currency",
    ):
        headers = column_map.get(column, (column,))
        values: List[str] = []
        for header in headers:
            entry = row.get(header)
            if entry is None:
                continue
            entry = entry.strip()
            if entry:
                values.append(entry)
        if not values:
            continue
        if column in TOKEN_COLUMNS:
            bucket: Any = None
            for raw in values:
                parsed = _coerce_value(column, raw, default_token)
                bucket = _merge_token_values(bucket, parsed)
            if bucket is not None:
                payload[column] = bucket
        else:
            payload[column] = _coerce_value(column, values[0], default_token)
    season_id = payload.get("season_id")
    if (
        fetch_season_window
        and season_id
        and ("season_start" not in payload or "season_end" not in payload)
    ):
        season_start, season_end = _ensure_season_window(season_id, season_api_template)
        if season_start:
            payload.setdefault("season_start", season_start)
        if season_end:
            payload.setdefault("season_end", season_end)
    if not payload.get("username"):
        raise ValueError("Username must be provided via --username or a username column.")
    return payload


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Upsert historical season rows for a single username into supabase."
    )
    parser.add_argument("csv_path", help="CSV file exported from your spreadsheet.")
    parser.add_argument(
        "--table",
        default=TABLE_NAME,
        help="Supabase table to upsert rows into (default: season_rewards).",
    )
    parser.add_argument(
        "--username",
        default="lorkus",
        help="Username baked into every payload unless a username column is provided.",
    )
    parser.add_argument(
        "--default-token",
        default="SPS",
        help="Token symbol to use when the token bucket column only contains a number.",
    )
    parser.add_argument(
        "--mapping",
        action="append",
        default=[],
        help="Map table fields to CSV headers (e.g., season_id=Season). Repeatable.",
    )
    parser.add_argument(
        "--key",
        default=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        help="Supabase service-role key (falls back to SUPABASE_SERVICE_ROLE_KEY).",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("SUPABASE_URL"),
        help="Supabase URL (falls back to SUPABASE_URL).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of rows to POST per request.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payloads without hitting Supabase (useful for confirming CSV headers).",
    )
    parser.add_argument(
        "--season-api",
        default=DEFAULT_SEASON_API,
        help="Template for fetching season details when the CSV lacks start/end (use {season_id}).",
    )
    parser.add_argument(
        "--fetch-season-window",
        action="store_true",
        help="Automatically fetch start/end ranges from the season API when missing (disabled by default).",
    )

    args = parser.parse_args()

    if not args.url or not args.key:
        parser.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set or passed via --url/--key.")

    column_map = _parse_mapping(args.mapping)

    payloads: List[Dict[str, Any]] = []
    with open(args.csv_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        if reader.fieldnames is None:
            parser.error("CSV file must have a header row.")
        for row in reader:
            try:
                row_payload = _build_payload(
                    row,
                    column_map,
                    args.default_token,
                    args.username,
                    args.season_api,
                    args.fetch_season_window,
                )
            except ValueError as exc:
                print(f"Skipping row {reader.line_num}: {exc}", file=sys.stderr)
                continue
            if not row_payload.get("season_id"):
                print(f"Skipping row {reader.line_num}: missing season_id", file=sys.stderr)
                continue
            payloads.append(row_payload)

    if not payloads:
        print("No valid rows to upsert.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("Dry run payloads:")
        for payload in payloads:
            print(json.dumps(payload))
        return

    headers = {
        "apikey": args.key,
        "Authorization": f"Bearer {args.key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    endpoint = f"{args.url}/rest/v1/{args.table}"
    for chunk in _chunked(payloads, args.batch_size):
        resp = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
        if resp.status_code >= 300:
            print(f"Upsert failed ({resp.status_code}): {resp.text}", file=sys.stderr)
            sys.exit(1)

    print(f"Upserted {len(payloads)} rows into {args.table}.")


if __name__ == "__main__":
    main()
