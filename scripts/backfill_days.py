"""
One-off backfill: re-fetch specific receivedate days that came up short
(a page failed mid-download in an earlier run). Uses your API key from .env.

Run in the venv, from the repo folder:
    python scripts/backfill_days.py

It does NOT delete anything first — a full re-fetch overwrites the partial
part-files and adds the missing ones.
"""

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("OPENFDA_API_KEY") or os.getenv("API_KEY")
URL = "https://api.fda.gov/drug/event.json"
RAW = Path(os.getenv("DATA_DIR", "D:/capstone/data")) / "bronze" / "drug_event"

DAYS = ["20230206", "20240704"]          # the short days to re-fetch


def get_page(day, skip):
    params = {"search": f"receivedate:[{day} TO {day}]", "limit": 1000, "skip": skip}
    if API_KEY:
        params["api_key"] = API_KEY
    for attempt in range(6):
        r = requests.get(URL, params=params, timeout=30)
        if r.status_code == 404:
            return []
        if r.status_code in (429, 500, 502, 503):
            time.sleep(min(2 ** attempt, 30))
            continue
        r.raise_for_status()
        return r.json().get("results", [])
    raise RuntimeError(f"page failed after retries: {day} skip={skip}")


for day in DAYS:
    d = RAW / f"receivedate={day}"
    d.mkdir(parents=True, exist_ok=True)
    total, skip = 0, 0
    while skip <= 25000:
        recs = get_page(day, skip)
        if not recs:
            break
        with open(d / f"part-{skip}.json", "w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec) + "\n")
        total += len(recs)
        if len(recs) < 1000:
            break
        skip += 1000
        time.sleep(0.3)
    print(f"{day}: re-fetched {total:,} records")

print("done")
