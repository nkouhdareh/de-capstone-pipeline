#!/usr/bin/env python
"""Export the DBT_DEV marts from Snowflake to local Parquet.

Insurance against the trial account expiring: everything app/dashboard_enhanced.py
reads is copied to DATA_DIR/offline/ so the dashboard can run with no warehouse.

fct_report_drug_reaction (45M rows / 1.7 GB) is copied as the drug_key column
alone, which is all the dashboard reads from it. Its two scalar counts are
also recorded in manifest.json.

Connects with the same key pair as everything else (app/db.py, ADR-012).

Usage:
    .venv-app/Scripts/python.exe scripts/export_marts_offline.py
    .venv-app/Scripts/python.exe scripts/export_marts_offline.py --only sem_signal_metrics
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from db import connect  # noqa: E402  (needs the path insert above)

OUT_DIR = Path(os.environ.get("DATA_DIR", "D:/capstone/data")) / "offline"

# Ordered smallest-first so a credential or permission problem surfaces in
# seconds rather than after the multi-minute view materialisation.
OBJECTS = [
    "signal_worked_example",
    "dim_date",
    "dim_reporter",
    "dim_drug",
    "dim_reaction",
    "int_drug_resolution",
    "fct_signal_metrics",
    "sem_signal_metrics",
    "fct_report_drug_reaction",
]

# Objects exported with something other than "select *".
# fct_report_drug_reaction is 45M rows / 1.7 GB, but the dashboard only ever
# reads drug_key from it (two counts). One narrow column keeps the offline
# table real rather than synthesised, at a fraction of the size.
CUSTOM_SQL = {
    "fct_report_drug_reaction": "select drug_key from fct_report_drug_reaction",
}

# The two numbers the dashboard takes from the 45M-row fact table.
SCALARS = {
    "fact_rows":
        "select count(*) from fct_report_drug_reaction",
    "unresolved_rows":
        "select count(*) from fct_report_drug_reaction where drug_key = -1",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def export_object(cursor, name: str) -> int:
    """Stream one table or view to Parquet in batches, so nothing is fully
    materialised in memory.

    Arrow batches, not pandas ones: fetch_pandas_batches() infers dtypes per
    batch independently, so a column can arrive as int8 in one batch and double
    in the next, which ParquetWriter rejects. Snowflake's Arrow batches carry
    the result set's own schema, so it is identical for every batch.

    Column names are lower-cased to match what the dashboard already expects
    from cursor.description.
    """
    target = OUT_DIR / f"{name}.parquet"
    started = time.perf_counter()
    log(f"{name}: querying ...")

    cursor.execute(CUSTOM_SQL.get(name, f"select * from {name}"))

    writer = None
    rows = 0
    try:
        for batch in cursor.fetch_arrow_batches():
            table = batch if isinstance(batch, pa.Table) else pa.Table.from_batches([batch])
            table = table.rename_columns([c.lower() for c in table.schema.names])

            if writer is None:
                writer = pq.ParquetWriter(target, table.schema, compression="snappy")
            elif table.schema != writer.schema:
                # Defensive: should not happen on the Arrow path, but a clear
                # failure beats a corrupt file.
                table = table.cast(writer.schema)

            writer.write_table(table)

            rows += table.num_rows
            print(f"    {rows:,} rows", end="\r", flush=True)
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        log(f"{name}: WARNING - no rows returned, nothing written")
        return 0

    mb = target.stat().st_size / 1e6
    log(f"{name}: {rows:,} rows -> {target.name} ({mb:.1f} MB) "
        f"in {time.perf_counter() - started:.0f}s")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", default=None,
                        help="export just this object (repeatable)")
    args = parser.parse_args()

    wanted = args.only or OBJECTS
    unknown = [w for w in wanted if w not in OBJECTS]
    if unknown:
        sys.exit(f"ERROR: unknown object(s): {', '.join(unknown)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"writing to {OUT_DIR}")

    manifest_path = OUT_DIR / "manifest.json"
    manifest = {"rows": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("rows", {})
        except (OSError, ValueError):
            manifest = {"rows": {}}
    manifest["exported_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    connection = connect()

    try:
        cursor = connection.cursor()
        cursor.execute("select current_user(), current_role(), current_warehouse()")
        log(f"connected as {cursor.fetchone()}")

        for name in wanted:
            manifest["rows"][name] = export_object(cursor, name)

        if not args.only:
            log("capturing scalars from fct_report_drug_reaction ...")
            scalars = {}
            for key, sql in SCALARS.items():
                cursor.execute(sql)
                scalars[key] = cursor.fetchone()[0]
                log(f"  {key} = {scalars[key]:,}")
            manifest["scalars"] = scalars

            cursor.execute("select max(_loaded_at), max(_run_id) from fct_signal_metrics")
            built_at, run_id = cursor.fetchone()
            manifest["built_at"] = str(built_at)
            manifest["run_id"] = run_id
            log(f"  built_at = {built_at}  run_id = {run_id}")
    finally:
        connection.close()

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"done. manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
