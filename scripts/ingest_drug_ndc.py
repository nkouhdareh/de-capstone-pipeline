"""
Ingest openFDA drug/ndc (National Drug Code directory) into the bronze layer,
using the bulk download files.

Why bulk files (not the paged API like drug/event):
- ndc has 136,520 records — past the API's 26,000 paging limit.
- The bulk file gets every record reliably in one pass, and needs no API key.

Saves raw NDJSON to DATA_DIR/bronze/drug_ndc/part-XXXX.json (one record per line).

Run from the repo folder:
    python scripts/ingest_drug_ndc.py
"""

import os
import io
import json
import zipfile
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = "ndc"                         # openFDA drug endpoint
INDEX_URL = "https://api.fda.gov/download.json"
MAX_FILES = None                         # None = all files; set e.g. 1 for a quick sample

RAW = Path(os.getenv("DATA_DIR", "D:/capstone/data")) / "bronze" / f"drug_{ENDPOINT}"
RAW.mkdir(parents=True, exist_ok=True)


def get_partitions():
    """Return the list of bulk files for this endpoint."""
    index = requests.get(INDEX_URL, timeout=60).json()
    return index["results"]["drug"][ENDPOINT]["partitions"]


def download_all():
    parts = get_partitions()
    if MAX_FILES:
        parts = parts[:MAX_FILES]
    print(f"drug/{ENDPOINT}: {len(parts)} bulk file(s) to download")

    total = 0
    for i, p in enumerate(parts):
        url = p["file"]
        print(f"[{i+1}/{len(parts)}] downloading {url} ...")
        resp = requests.get(url, timeout=600)
        resp.raise_for_status()
        blob = resp.content                        # the .zip, in memory
        zf = zipfile.ZipFile(io.BytesIO(blob))
        inner = zf.namelist()[0]                   # one .json inside the zip
        data = json.loads(zf.read(inner).decode("utf-8"))
        records = data.get("results", [])

        out = RAW / f"part-{i:04d}.json"
        with open(out, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")    # one record per line (NDJSON)
        total += len(records)
        print(f"    saved {len(records):,} records -> {out.name}  (total {total:,})")

    print(f"\nDONE. {total:,} records saved to {RAW}")


if __name__ == "__main__":
    download_all()
