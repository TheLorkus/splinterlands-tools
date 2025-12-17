from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv


def _parse_ends(season_data: dict) -> datetime:
    ends_raw = season_data.get("ends") or season_data.get("end") or season_data.get("season", {}).get("ends")
    if not ends_raw:
        raise RuntimeError("No season end timestamp found in API response.")
    return datetime.fromisoformat(str(ends_raw).replace("Z", "+00:00"))


def _cron_for_target(target: datetime) -> str:
    return f"{target.minute} {target.hour} {target.day} {target.month} *"


def main() -> None:
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not service_key:
        print(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY must be set in the environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    season_endpoint = os.getenv("SYNC_SEASON_ENDPOINT", "https://api.splinterlands.com/season?id=171")
    schedule_name = os.getenv("SYNC_SCHEDULE_NAME", "season-sync")
    function_name = os.getenv("SYNC_FUNCTION_NAME", "season-sync")

    resp = requests.get(season_endpoint, timeout=30)
    resp.raise_for_status()
    season = resp.json() or {}
    season_end = _parse_ends(season) - timedelta(minutes=10)
    cron_expression = _cron_for_target(season_end)

    payload = {
        "name": schedule_name,
        "cron": cron_expression,
        "timezone": "UTC",
        "enabled": True,
        "target": function_name,
        "target_type": "function",
    }

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    rpc_url = f"{supabase_url}/rest/v1/rpc/supabase_scheduler"
    resp = requests.post(rpc_url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()

    print(f"Updated schedule '{schedule_name}' to run at {season_end.isoformat()} UTC ({cron_expression}).")


if __name__ == "__main__":
    main()
