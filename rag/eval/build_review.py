"""Phase 2, step 3: the spreadsheet for reviewing the drafted questions.

Joins every draft to the chunk it was written from, marks the answer inside the
chunk as >>>answer<<< so it is found at a glance, and re-checks that every
marked answer really exists in its chunk.

The reviewer fills one column, verdict: ok, fix or drop. For fix, the corrected
question goes in fixed_question. Nothing else in the sheet is read back, so
sorting or filtering it in Excel is safe.

Output: data/rag/gold_review.csv. Gitignored: the reviewed sheet becomes the
committed gold set in the next step.

Usage:
    python -m rag.eval.build_review
"""
from __future__ import annotations

import csv
import json
from collections import Counter

import duckdb

RAGDATA = "D:/capstone/data/rag"
DRAFTS = f"{RAGDATA}/gold_drafts.jsonl"
CONTENT = f"{RAGDATA}/gold_candidates.jsonl"
VERIFY = f"{RAGDATA}/gold_verify_candidates.jsonl"
NEGATIVE = f"{RAGDATA}/gold_negative_candidates.jsonl"
CHUNKS = f"{RAGDATA}/chunks.parquet"
OUT = f"{RAGDATA}/gold_review.csv"

# Reviewer columns first, so they sit on the left in Excel.
COLUMNS = ["draft_id", "verdict", "fixed_question", "notes",
           "qtype", "question", "answer_span", "drug", "brand", "section",
           "chunk_with_answer_marked", "rationale", "negative_kind", "candidate_id"]

NO_CHUNK = "(no chunk: the correct answer is 'outside indexed scope')"


def excel_delimiter() -> str:
    """Excel splits a CSV on the Windows list separator, which is ';' on many
    European locales. Reading it means a double-click opens the file cleanly."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as key:
            return winreg.QueryValueEx(key, "sList")[0] or ","
    except (ImportError, OSError):
        return ","


def safe(value: str) -> str:
    """Excel treats a cell starting with = + - @ as a formula, and label text
    can start with '- Bleeding', which would display as #NAME?."""
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def load(path: str, key: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return {row[key]: row for row in map(json.loads, fh)}


def main() -> None:
    with open(DRAFTS, encoding="utf-8") as fh:
        drafts = [json.loads(line) for line in fh]
    content = load(CONTENT, "candidate_id")
    verify = load(VERIFY, "vcand_id")
    negative = load(NEGATIVE, "ncand_id")

    ids = [v["chunk_id"] for v in verify.values()]
    text_by_chunk = dict(duckdb.connect().execute(
        f"SELECT chunk_id, text FROM '{CHUNKS}' WHERE list_contains(?, chunk_id)",
        [ids]).fetchall())

    rows, missing = [], []
    for d in drafts:
        cid = d.get("candidate_id") or ""
        if cid.startswith("c"):
            c = content[cid]
            text, drug, brand, section = c["text"], c["generic_name"], c["brand_name"], c["section"]
        elif cid.startswith("v"):
            v = verify[cid]
            text = text_by_chunk.get(v["chunk_id"], "")
            drug, brand, section = v["generic_name"], v["brand_name"], v["section"]
        else:
            text, brand, section = "", "", ""
            drug = negative[cid]["drug_name"] if cid.startswith("n") else d.get("drug", "")

        span = d.get("answer_span") or ""
        if not span:
            marked = NO_CHUNK
        elif span in text:
            marked = text.replace(span, f">>>{span}<<<", 1)
        else:
            marked = text
            missing.append(d["draft_id"])

        rows.append({
            "draft_id": d["draft_id"], "verdict": "", "fixed_question": "", "notes": "",
            "qtype": d["qtype"], "question": d["question"], "answer_span": safe(span),
            "drug": drug or "", "brand": brand or "", "section": section,
            "chunk_with_answer_marked": safe(marked),
            "rationale": d.get("rationale", ""),
            "negative_kind": d.get("negative_kind") or "", "candidate_id": cid,
        })

    delim = excel_delimiter()
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=delim)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} questions written to {OUT}  (delimiter {delim!r})")
    for qtype, n in Counter(r["qtype"] for r in rows).most_common():
        print(f"  {qtype:<12} {n}")
    print(f"answers not found in their chunk: {len(missing)} {missing or ''}")


if __name__ == "__main__":
    main()
