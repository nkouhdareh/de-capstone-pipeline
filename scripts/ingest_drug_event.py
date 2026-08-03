"""
Ingest openFDA drug/event (FAERS) records into the bronze layer.

What it does:
- Pulls day by day (date windows) so it never hits openFDA's 26,000 skip limit.
- Pages 1,000 records per request until each day is finished.
- Saves raw JSON to DATA_DIR/bronze/drug_event/ (on the D: drive, not the repo).
- Stops at TARGET records, or when END date is reached.

Run from the repo folder:
    python scripts/ingest_drug_event.py

Needs a .env file with:
    OPENFDA_API_KEY=your_key_here
    DATA_DIR=D:/capstone/data
"""

import os
import json
import time
import requests
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("OPENFDA_API_KEY") or os.getenv("API_KEY")  # accept either name

# Save BIG data on the D: drive, never in the repo
RAW = Path(os.getenv("DATA_DIR", "D:/capstone/data")) / "bronze" / "drug_event"
RAW.mkdir(parents=True, exist_ok=True)

URL = "https://api.fda.gov/drug/event.json"

TARGET = 3_000_000          # stop after ~3 million records
LIMIT = 1000                # max records per request
MAX_SKIP = 25000            # openFDA rule: skip + limit <= 26000

START = date(2023, 1, 1)    # which dates to pull (2023-2024 ~= 2.69 million)
END = date(2024, 12, 31)


def get_page(day_str, skip):
    """One API call. Returns a list of records (empty if none)."""
    params = {"search": f"receivedate:[{day_str} TO {day_str}]",
              "limit": LIMIT, "skip": skip}
    if API_KEY:
        params["api_key"] = API_KEY

    for attempt in range(6):                    # retry on rate-limit / server errors
        r = requests.get(URL, params=params, timeout=30)
        if r.status_code == 404:                # openFDA = "no results for this day"
            return []
        if r.status_code in (429, 500, 502, 503):
            time.sleep(min(2 ** attempt, 30))   # wait longer each try (capped at 30s)
            continue
        r.raise_for_status()
        return r.json().get("results", [])
    # all retries failed -> fail LOUDLY, never silently end the day early
    raise RuntimeError(f"openFDA page failed after retries: {day_str} skip={skip}")


def download_events():
    total = 0
    day = START
    while day <= END and total < TARGET:
        day_str = day.strftime("%Y%m%d")
        skip = 0
        while skip <= MAX_SKIP and total < TARGET:
            records = get_page(day_str, skip)
            if not records:
                break                           # this day is done
            day_dir = RAW / f"receivedate={day_str}"
            day_dir.mkdir(parents=True, exist_ok=True)
            out = day_dir / f"part-{skip}.json"
            with open(out, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec) + "\n")   # one record per line (NDJSON)
            total += len(records)
            print(f"{day_str}  skip={skip}  got={len(records)}  total={total:,}")
            if len(records) < LIMIT:
                break                           # last page for this day
            skip += LIMIT
            time.sleep(0.3)                     # polite: ~200/min, under the limit
        day += timedelta(days=1)

    print(f"\nDONE. {total:,} records saved to {RAW}")


if __name__ == "__main__":
    download_events()
