#!/usr/bin/env python
"""Load local Silver Parquet + NDC NDJSON into Snowflake RAW via internal stages.

Credentials come from environment variables ONLY (never printed, never committed):
    SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD
Non-secret connection settings are fixed to the capstone objects:
    role DE_CAPSTONE_DBT_ROLE / warehouse DE_CAPSTONE_WH / database DE_CAPSTONE / schema RAW

Usage:
    python load_to_snowflake.py                 # load Silver (all months) + NDC
    python load_to_snowflake.py --what silver   # only Silver
    python load_to_snowflake.py --what ndc      # only NDC
    python load_to_snowflake.py --max-partitions 1   # smoke test: 1 month of Silver
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()  # convenience for DATA_DIR; does NOT override real OS env vars
except Exception:
    pass

import snowflake.connector

HERE = Path(__file__).resolve().parent
DDL_FILE = HERE / "ddl_raw.sql"
DATA_DIR = Path(os.environ.get("DATA_DIR", "D:/capstone/data"))
SILVER_DIR = DATA_DIR / "silver" / "drug_event"
NDC_FILE = DATA_DIR / "bronze" / "drug_ndc" / "part-0000.json"

REQUIRED = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def connect():
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        sys.exit(
            "ERROR: missing environment variable(s): "
            + ", ".join(missing)
            + "\nSet them in your shell (values are never read from chat), e.g. PowerShell:\n"
            + '  setx SNOWFLAKE_ACCOUNT "<account_locator>"\n'
            + '  setx SNOWFLAKE_USER "<user>"\n'
            + '  setx SNOWFLAKE_PASSWORD "<password>"\n'
            + "then open a NEW shell so the values are inherited."
        )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role="DE_CAPSTONE_DBT_ROLE",
        warehouse="DE_CAPSTONE_WH",
        database="DE_CAPSTONE",
        schema="RAW",
        autocommit=True,
        application="de_capstone_loader",
    )


def run_ddl(cur) -> None:
    log("running RAW DDL (file formats, stages, tables) ...")
    for stmt in cur.connection.execute_string(DDL_FILE.read_text(encoding="utf-8")):
        pass
    log("DDL done.")


def as_put_uri(p: Path) -> str:
    # Snowflake PUT wants forward slashes; single-quote to survive '=' in paths.
    return "file://" + str(p).replace("\\", "/")


def load_silver(cur, max_partitions: int) -> None:
    if not SILVER_DIR.is_dir():
        sys.exit(f"ERROR: Silver dir not found: {SILVER_DIR}")
    parts = sorted(
        glob.glob(str(SILVER_DIR / "receive_year=*" / "receive_month=*")),
        key=lambda s: tuple(int(x) for x in re.findall(r"=(\d+)", s)),
    )
    if max_partitions and max_partitions > 0:
        parts = parts[:max_partitions]
    log(f"Silver: {len(parts)} month-partition(s) to load")

    log("clearing SILVER_STAGE and truncating RAW.SILVER_DRUG_EVENT ...")
    cur.execute("REMOVE @RAW.SILVER_STAGE")
    cur.execute("TRUNCATE TABLE RAW.SILVER_DRUG_EVENT")

    t0 = time.time()
    for i, part in enumerate(parts, 1):
        y, m = re.findall(r"=(\d+)", part)
        uri = as_put_uri(Path(part) / "*.parquet")
        # Parquet is already snappy-compressed -> AUTO_COMPRESS=FALSE.
        cur.execute(
            f"PUT '{uri}' @RAW.SILVER_STAGE/y={y}/m={m}/ "
            "AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=8"
        )
        log(f"  [{i}/{len(parts)}] staged {y}-{int(m):02d}")
    log(f"PUT complete in {time.time() - t0:.0f}s; COPY INTO RAW.SILVER_DRUG_EVENT ...")

    cur.execute(
        "COPY INTO RAW.SILVER_DRUG_EVENT FROM @RAW.SILVER_STAGE "
        "FILE_FORMAT = (FORMAT_NAME = RAW.FF_PARQUET) "
        "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE "
        "PATTERN = '.*[.]parquet' "
        "ON_ERROR = 'ABORT_STATEMENT'"
    )
    n = cur.execute("SELECT COUNT(*) FROM RAW.SILVER_DRUG_EVENT").fetchone()[0]
    log(f"Silver loaded: {n:,} rows in RAW.SILVER_DRUG_EVENT")


def load_ndc(cur) -> None:
    if not NDC_FILE.is_file():
        sys.exit(f"ERROR: NDC file not found: {NDC_FILE}")
    log("clearing NDC_STAGE and truncating RAW.DRUG_NDC ...")
    cur.execute("REMOVE @RAW.NDC_STAGE")
    cur.execute("TRUNCATE TABLE RAW.DRUG_NDC")

    log(f"PUT NDC file ({NDC_FILE.stat().st_size / 1e6:.0f} MB, auto-gzip) ...")
    cur.execute(
        f"PUT '{as_put_uri(NDC_FILE)}' @RAW.NDC_STAGE "
        "AUTO_COMPRESS=TRUE OVERWRITE=TRUE PARALLEL=8"
    )
    log("COPY INTO RAW.DRUG_NDC ...")
    cur.execute(
        "COPY INTO RAW.DRUG_NDC FROM @RAW.NDC_STAGE "
        "FILE_FORMAT = (FORMAT_NAME = RAW.FF_JSON) "
        "ON_ERROR = 'ABORT_STATEMENT'"
    )
    n = cur.execute("SELECT COUNT(*) FROM RAW.DRUG_NDC").fetchone()[0]
    log(f"NDC loaded: {n:,} rows in RAW.DRUG_NDC")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--what", choices=["all", "silver", "ndc"], default="all")
    ap.add_argument("--max-partitions", type=int, default=0,
                    help="Silver only: load first N month-partitions (0 = all). Smoke test with 1.")
    args = ap.parse_args()

    conn = connect()
    try:
        cur = conn.cursor()
        log(f"connected: account={os.environ['SNOWFLAKE_ACCOUNT']} "
            f"role=DE_CAPSTONE_DBT_ROLE wh=DE_CAPSTONE_WH db=DE_CAPSTONE schema=RAW")
        run_ddl(cur)
        if args.what in ("all", "ndc"):
            load_ndc(cur)
        if args.what in ("all", "silver"):
            load_silver(cur, args.max_partitions)
        log("done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
