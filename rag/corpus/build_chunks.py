"""Phase 1 driver: turn Bronze SPL labels into a chunk table.

Streams the raw JSONL, applies the scope filter, chunks with rag.corpus.chunker,
and writes Parquet. Deduplication runs afterwards in DuckDB rather than in
Python, because holding ~692k chunks in memory to group them costs 2-3 GB.

Outputs:
  data/rag/chunks_raw.parquet  every chunk, duplicates included
  data/rag/chunks.parquet      deduplicated, one row per distinct chunk text
  data/rag/sections.parquet    parent section text for small-to-big retrieval

Usage:
  python rag/corpus/build_chunks.py --limit 500   # smoke test, ~20s
  python rag/corpus/build_chunks.py               # full run
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import time

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from rag.corpus.chunker import (
    CHUNKER_VERSION,
    OTC_GROUP_NAME,
    OTC_SAFETY_GROUP,
    RX_SECTIONS,
    chunk_section,
    context_header,
    merge_otc_safety,
    normalise_whitespace,
    token_counter,
)

BRONZE = "D:/capstone/data/bronze/drug_label"
RAGDATA = "D:/capstone/data/rag"
RAW = f"{RAGDATA}/chunks_raw.parquet"
CHUNKS = f"{RAGDATA}/chunks.parquet"
SECTIONS = f"{RAGDATA}/sections.parquet"

BATCH = 5_000  # records per Parquet flush; keeps peak memory flat

CHUNK_SCHEMA = pa.schema([
    ("chunk_id",          pa.string()),
    ("set_id",            pa.string()),
    ("product_ndc",       pa.string()),
    ("product_type",      pa.string()),
    ("brand_name",        pa.string()),
    ("generic_name",      pa.string()),
    ("manufacturer_name", pa.string()),
    ("section",           pa.string()),
    ("is_merged",         pa.bool_()),
    ("part_i",            pa.int16()),
    ("part_n",            pa.int16()),
    ("n_tokens",          pa.int32()),
    ("n_chars",           pa.int32()),
    ("text_hash",         pa.binary(8)),
    ("text",              pa.string()),
    ("text_with_header",  pa.string()),
    ("chunker_version",   pa.string()),
])

SECTION_SCHEMA = pa.schema([
    ("set_id",  pa.string()),
    ("section", pa.string()),
    ("text",    pa.string()),
])


def first(block: dict, key: str) -> str | None:
    """openfda values are lists; take the first. Phase 0 showed one NDC per
    label among attributable records, so the first is the label's own."""
    v = block.get(key)
    return str(v[0]) if isinstance(v, list) and v else None


def section_text(rec: dict, name: str) -> str:
    """Every section is array<string> (Phase 0: 183 field paths, one exception
    and it is not a section). Join, do not dispatch on type."""
    v = rec.get(name)
    return "\n\n".join(v) if isinstance(v, list) and v else ""


def label_meta(rec: dict) -> dict:
    o = rec["openfda"]
    return {
        "set_id":            rec.get("set_id"),
        "product_ndc":       first(o, "product_ndc"),
        "product_type":      first(o, "product_type"),
        "brand_name":        first(o, "brand_name"),
        "generic_name":      first(o, "generic_name"),
        "manufacturer_name": first(o, "manufacturer_name"),
    }


def blake8(text: str) -> bytes:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()


def emit(meta: dict, section: str, pieces: list[str], is_merged: bool,
         count_tokens) -> list[dict]:
    """Turn chunked pieces into rows, attaching the context header.

    chunk_id is deterministic on (set_id, section, part_i) so a rebuild with an
    unchanged chunker produces identical ids, which is what makes the index a
    reproducible artifact rather than a snapshot.
    """
    rows = []
    drug = meta["generic_name"] or meta["brand_name"] or ""
    n = len(pieces)
    for i, piece in enumerate(pieces, start=1):
        header = context_header(drug, meta["brand_name"] or "",
                                meta["manufacturer_name"] or "",
                                section.replace("_", " ").title(), i, n)
        rows.append({
            **meta,
            "chunk_id": hashlib.blake2b(
                f"{meta['set_id']}|{section}|{i}".encode(), digest_size=16).hexdigest(),
            "section": section,
            "is_merged": is_merged,
            "part_i": i,
            "part_n": n,
            "n_tokens": count_tokens(piece),
            "n_chars": len(piece),
            "text_hash": blake8(piece),
            "text": piece,
            "text_with_header": f"{header}\n\n{piece}",
            "chunker_version": CHUNKER_VERSION,
        })
    return rows


def chunks_for_record(rec: dict, count_tokens):
    """Yield (chunk rows, parent section rows) for one label."""
    meta = label_meta(rec)
    chunks, parents = [], []

    for name in RX_SECTIONS:
        text = normalise_whitespace(section_text(rec, name))
        if not text:
            continue
        pieces = chunk_section(text, count_tokens)
        if not pieces:
            continue
        chunks += emit(meta, name, pieces, False, count_tokens)
        parents.append({"set_id": meta["set_id"], "section": name, "text": text})

    # The six OTC safety fields average ~160 chars each. Merged they are one
    # coherent Drug Facts panel; separately they are six vectors of noise.
    merged = merge_otc_safety({n: section_text(rec, n) for n in OTC_SAFETY_GROUP})
    if merged:
        pieces = chunk_section(merged, count_tokens)
        if pieces:
            chunks += emit(meta, OTC_GROUP_NAME, pieces, True, count_tokens)
            parents.append({"set_id": meta["set_id"],
                            "section": OTC_GROUP_NAME, "text": merged})
    return chunks, parents


def deduplicate() -> None:
    """One text may appear on thousands of labels (Phase 0: a `warnings` text on
    6,390). Keep one representative and record how many labels carry it, so the
    UI can still say so instead of the fact being silently lost."""
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *,
                       count(*)      OVER w AS n_labels,
                       row_number()  OVER (PARTITION BY section, text_hash
                                           ORDER BY set_id) AS rn
                FROM '{RAW}'
                WINDOW w AS (PARTITION BY section, text_hash)
            )
            WHERE rn = 1
        ) TO '{CHUNKS}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="max records per part file; 0 = all")
    args = ap.parse_args()

    parts = sorted(glob.glob(f"{BRONZE}/part-*.json"))
    if not parts:
        raise SystemExit(f"no part files under {BRONZE}")
    os.makedirs(RAGDATA, exist_ok=True)
    count_tokens = token_counter()

    cw = pq.ParquetWriter(RAW, CHUNK_SCHEMA, compression="zstd")
    sw = pq.ParquetWriter(SECTIONS, SECTION_SCHEMA, compression="zstd")
    cbuf: list[dict] = []
    sbuf: list[dict] = []
    seen = kept = n_chunks = 0
    t0 = time.time()

    def flush():
        if cbuf:
            cw.write_table(pa.Table.from_pylist(cbuf, schema=CHUNK_SCHEMA))
            cbuf.clear()
        if sbuf:
            sw.write_table(pa.Table.from_pylist(sbuf, schema=SECTION_SCHEMA))
            sbuf.clear()

    for path in parts:
        with open(path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if args.limit and i >= args.limit:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seen += 1
                # Scope filter. Test the VALUE: `openfda` is a key on 100% of
                # records but empty on 66.9% of them (Phase 0).
                if not rec.get("openfda"):
                    continue
                kept += 1
                rows, parents = chunks_for_record(rec, count_tokens)
                cbuf += rows
                sbuf += parents
                n_chunks += len(rows)
                if kept % BATCH == 0:
                    flush()
        print(f"  {os.path.basename(path)}  seen {seen:,}  kept {kept:,}  "
              f"chunks {n_chunks:,}  ({time.time()-t0:.0f}s)", flush=True)

    flush()
    cw.close()
    sw.close()
    print(f"\nchunked {kept:,} of {seen:,} labels -> {n_chunks:,} raw chunks "
          f"in {time.time()-t0:.0f}s")

    print("deduplicating in DuckDB ...")
    deduplicate()

    con = duckdb.connect()
    kept_chunks, max_tok, over = con.execute(f"""
        SELECT count(*), max(n_tokens), count(*) FILTER (WHERE n_tokens > 512)
        FROM '{CHUNKS}'
    """).fetchone()
    print(f"\n{'=' * 66}")
    print(f"raw chunks        {n_chunks:,}")
    print(f"after dedup       {kept_chunks:,}  "
          f"({100 * (1 - kept_chunks / max(n_chunks, 1)):.1f}% removed)")
    print(f"max tokens        {max_tok}")
    print(f"chunks over 512   {over}   <- GATE: must be 0")
    print(f"gate 150k-700k    {'PASS' if 150_000 <= kept_chunks <= 700_000 else 'CHECK'}")
    print(f"{'=' * 66}")
    for f in (RAW, CHUNKS, SECTIONS):
        print(f"  {f}  {os.path.getsize(f) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
