"""Phase 2, step 1: draw the chunks that gold questions will be written from.

A gold set has to test every section and label type, not just the most common
ones. adverse_reactions alone is 19% of all chunks, so sampling in proportion
would give a gold set that mostly tests one section. This draws the same
number from each section instead, and at most one chunk per drug per section.

Deterministic on purpose. The order comes from md5(chunk_id + SALT), which is
stable across machines and DuckDB versions (a seeded random() is not), so the
same candidates come back every time and the gold set's origin is reproducible.

Output: data/rag/gold_candidates.jsonl. Gitignored, because it is raw material
for questions rather than the gold set itself, and this script rebuilds it.

Usage:
    python -m rag.eval.sample_candidates
"""
from __future__ import annotations

import json
import os
from collections import Counter

import duckdb

RAGDATA = "D:/capstone/data/rag"
CHUNKS = f"{RAGDATA}/chunks.parquet"
OUT = f"{RAGDATA}/gold_candidates.jsonl"

SALT = "gold-v1"     # change only to draw a deliberately different sample
PER_SECTION = 12     # 11 sections x 12 = 132 candidates, about 2x what we need
MIN_TOKENS = 100     # shorter chunks rarely hold a fact worth a question

QUERY = f"""
WITH eligible AS (
    SELECT *, md5(chunk_id || '{SALT}') AS draw
    FROM '{CHUNKS}'
    WHERE n_tokens >= {MIN_TOKENS}
      AND generic_name IS NOT NULL
),
one_per_drug AS (
    SELECT * FROM eligible
    QUALIFY row_number() OVER (
        PARTITION BY section, upper(generic_name) ORDER BY draw) = 1
)
SELECT draw, chunk_id, set_id, section, product_type, generic_name,
       brand_name, manufacturer_name, product_ndc, part_i, part_n,
       n_tokens, n_labels, text
FROM one_per_drug
QUALIFY row_number() OVER (PARTITION BY section ORDER BY draw) <= {PER_SECTION}
ORDER BY section, draw
"""


def main() -> None:
    if not os.path.exists(CHUNKS):
        raise SystemExit(f"{CHUNKS} not found. Run Phase 1 first: "
                         "python -m rag.corpus.build_chunks")
    con = duckdb.connect()
    cur = con.execute(QUERY)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    with open(OUT, "w", encoding="utf-8") as fh:
        for i, row in enumerate(rows, start=1):
            row.pop("draw")
            fh.write(json.dumps({"candidate_id": f"c{i:03d}", **row},
                                ensure_ascii=False) + "\n")

    print(f"{len(rows)} candidates written to {OUT}")
    print(f"distinct drugs: {len({r['generic_name'].upper() for r in rows})}\n")
    print("by section:")
    for name, n in sorted(Counter(r["section"] for r in rows).items()):
        print(f"  {name:30} {n}")
    print("\nby label type:")
    for name, n in Counter(r["product_type"] for r in rows).most_common():
        print(f"  {str(name):30} {n}")

    first = rows[0]
    print(f"\nexample: {first['generic_name']} | {first['section']} | "
          f"part {first['part_i']} of {first['part_n']} | {first['n_tokens']} tokens")
    print(first["text"][:400] + " ...")


if __name__ == "__main__":
    main()
