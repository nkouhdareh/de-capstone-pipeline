"""The gold set and its resolver: anchors in, chunk ids out.

gold.jsonl stores an anchor, (set_id, section, answer_span), and never a chunk
id. Chunk ids are a function of the chunker: change the target size in Phase 5
and every id changes, which would silently rot an evaluation set built in Phase
2. An anchor is a fact about the label instead, so it survives re-chunking.

Resolving one has to go through chunks_raw.parquet, not chunks.parquet.
Deduplication keeps one row per (section, text_hash) and drops the rest, and
57.6% of raw chunks were duplicates, so the label a question was written from is
often not the label whose row survived. Looking an anchor up in chunks.parquet
directly would miss every question whose own label lost that tie-break. The
route is:

    anchor -> the raw chunks of that label and section containing the span
           -> their (section, text_hash)
           -> the chunk id deduplication kept for that text

which is the id a retriever can actually return. Those are the STRICT answers.

The same answer on another label counts too. Phase 3's first run scored 0.294
recall@5, and a diagnosis of its 48 misses found 16 were correct: the answer,
word for word, from another manufacturer's label of the same drug, chunked at
different boundaries. So a question's RELEVANT chunks are its strict ones plus
every chunk in the same section, holding the same answer text, for the same
drug. For identifier questions "the same drug" means the same brand, because
they name one product. The strict sets are kept, and reported beside the rest.

Negatives carry no anchor. Their answer is not in the corpus, which is the point
of having them.

The matching rules are pure functions, so their tests need no corpus, no duckdb
and no network. duckdb is imported only by the two functions that read disk.

Usage:
    python -m rag.eval.gold        # resolve the whole gold set and report
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

RAGDATA = "D:/capstone/data/rag"
CHUNKS = f"{RAGDATA}/chunks.parquet"
RAW = f"{RAGDATA}/chunks_raw.parquet"
GOLD = Path(__file__).resolve().parent / "gold" / "gold.jsonl"

SPLITS = ("dev", "test")
QTYPES = ("lookup", "verify", "paraphrase", "identifier", "negative")

# Words that do not change which drug a name means: salts and filler (the list
# signal_candidates.py uses) plus dosage forms, which label names often carry,
# as in LISINOPRIL AND HYDROCHLOROTHIAZIDE TABLETS.
IGNORED_WORDS = frozenset({
    "HYDROCHLORIDE", "HCL", "HYDROBROMIDE", "HBR", "SODIUM", "POTASSIUM", "CALCIUM",
    "MAGNESIUM", "ZINC", "BROMIDE", "CHLORIDE", "SULFATE", "PHOSPHATE", "ACETATE",
    "CITRATE", "MALEATE", "FUMARATE", "SUCCINATE", "TARTRATE", "BITARTRATE",
    "MESYLATE", "BESYLATE", "TOSYLATE", "LACTATE", "GLUCONATE", "CARBONATE",
    "BICARBONATE", "NITRATE", "OXALATE", "PROPIONATE", "DIPROPIONATE", "FUROATE",
    "VALERATE", "TRIFENATATE", "XINAFOATE", "MONOHYDRATE", "DIHYDRATE", "HYDRATE",
    "ANHYDROUS", "DISODIUM", "ACID", "AND", "WITH", "TRIHYDRATE", "SESQUIHYDRATE",
    "DIETHYLAMINE", "EPOLAMINE",
    "TABLET", "TABLETS", "CAPSULE", "CAPSULES", "INJECTION", "INJECTABLE", "USP",
    "ORAL", "ORALLY", "SOLUTION", "SUSPENSION", "EXTENDED", "DELAYED", "RELEASE",
    "ER", "XR", "DR", "SR", "FILM", "COATED", "CHEWABLE", "DISINTEGRATING", "FOR",
    "TOPICAL", "CREAM", "OINTMENT", "GEL", "KIT",
})


class Anchor(NamedTuple):
    qid: str
    set_id: str
    section: str
    answer_span: str


class Resolution(NamedTuple):
    relevant: dict      # qid -> chunk ids holding its answer: strict, plus other labels'
    unresolved: list    # qids whose anchor matched nothing in the current index
    negatives: list     # qids with no anchor, by design
    strict: dict        # qid -> only the chunks from the label it was written from


def load_gold(path=GOLD, split: str | None = None) -> list[dict]:
    """Read gold.jsonl and check it before anything downstream trusts it."""
    with open(path, encoding="utf-8") as fh:
        questions = [json.loads(line) for line in fh if line.strip()]

    seen = set()
    for question in questions:
        qid = question.get("qid")
        if not qid:
            raise ValueError("a gold question has no qid")
        if qid in seen:
            raise ValueError(f"{qid}: repeated qid")
        seen.add(qid)
        if question.get("split") not in SPLITS:
            raise ValueError(f"{qid}: split {question.get('split')!r} is not dev or test")
        if question.get("qtype") not in QTYPES:
            raise ValueError(f"{qid}: unknown qtype {question.get('qtype')!r}")
        if (question["qtype"] == "negative") != (question.get("anchor") is None):
            raise ValueError(f"{qid}: negatives must carry no anchor, and every other "
                             "question must carry one")

    if split is not None:
        if split not in SPLITS:
            raise ValueError(f"split {split!r} is not dev or test")
        questions = [q for q in questions if q["split"] == split]
    return questions


def anchors_of(questions: Iterable[dict]) -> list[Anchor]:
    return [Anchor(q["qid"], q["anchor"]["set_id"], q["anchor"]["section"],
                   q["anchor"]["answer_span"])
            for q in questions if q.get("anchor")]


def drug_tokens(name: str | None) -> frozenset:
    """A drug name's significant words. DULOXETINE HYDROCHLORIDE and Duloxetine
    both become {DULOXETINE}; AMLODIPINE BESYLATE AND BENAZEPRIL becomes
    {AMLODIPINE, BENAZEPRIL}, which is a different product. Text only, never
    drug_key."""
    return frozenset(word for word in re.findall(r"[A-Z0-9]+", (name or "").upper())
                     if word not in IGNORED_WORDS)


def match_anchors(anchors: Iterable[Anchor], raw_rows, canonical) -> tuple[dict, list]:
    """Pure core: which chunk ids of the current index answer each anchor.

    raw_rows:  (set_id, section, text_hash, text) for the anchored labels,
               duplicates included, straight from chunks_raw.
    canonical: (section, text_hash) -> chunk_id, the row dedup kept.

    Matching is an exact substring test, because finalize_gold only accepts a
    span that appears in its chunk word for word. A span that no longer matches
    is reported as unresolved rather than quietly dropped or fuzzily rescued:
    after a re-chunk, that report is the signal that a boundary moved.
    """
    by_label = defaultdict(list)
    for set_id, section, text_hash, text in raw_rows:
        by_label[(set_id, section)].append((text_hash, text))

    relevant, unresolved = {}, []
    for anchor in anchors:
        found = set()
        for text_hash, text in by_label.get((anchor.set_id, anchor.section), ()):
            if anchor.answer_span in text:
                chunk_id = canonical.get((anchor.section, text_hash))
                if chunk_id is not None:
                    found.add(chunk_id)
        if found:
            relevant[anchor.qid] = frozenset(found)
        else:
            unresolved.append(anchor.qid)
    return relevant, unresolved


def match_equivalents(questions: Iterable[dict], rows) -> dict:
    """Pure core: chunks on other labels that hold the same answer.

    rows: (qid, chunk_id, generic_name, brand_name) for every chunk in the
          anchor's section whose text contains the answer span, on any label.

    A row counts when its drug is the question's drug: the same significant words
    in the generic name or, for identifier questions, in the brand name. A name
    with no significant words never matches, so an unclear case stays strict.
    """
    by_qid = {q["qid"]: q for q in questions if q.get("anchor")}
    found = defaultdict(set)
    for qid, chunk_id, generic, brand in rows:
        question = by_qid.get(qid)
        if question is None:
            continue
        if question["qtype"] == "identifier":
            want, have = drug_tokens(question.get("brand")), drug_tokens(brand)
        else:
            want, have = drug_tokens(question.get("drug")), drug_tokens(generic)
        if want and want == have:
            found[qid].add(chunk_id)
    return {qid: frozenset(ids) for qid, ids in found.items()}


def fetch(anchors: Iterable[Anchor], raw: str = RAW, chunks: str = CHUNKS):
    """Reads the rows match_anchors needs.

    Filtering on (set_id, section) before reading text keeps this under a
    second. Joining the anchors straight against 851,377 raw chunks makes
    DuckDB read every chunk's text instead of a few hundred.
    """
    import duckdb

    anchors = list(anchors)
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE labels(set_id VARCHAR, section VARCHAR)")
    con.executemany("INSERT INTO labels VALUES (?, ?)",
                    sorted({(a.set_id, a.section) for a in anchors}))
    raw_rows = con.execute(f"""
        SELECT r.set_id, r.section, r.text_hash, r.text
        FROM '{raw}' r SEMI JOIN labels l
          ON l.set_id = r.set_id AND l.section = r.section
    """).fetchall()

    # The surviving row for a text may belong to a different label, so this
    # lookup is keyed on the text, never on the anchor's set_id.
    con.execute("CREATE TEMP TABLE texts(section VARCHAR, text_hash BLOB)")
    con.executemany("INSERT INTO texts VALUES (?, ?)",
                    sorted({(section, text_hash) for _, section, text_hash, _ in raw_rows}))
    canonical = {(section, text_hash): chunk_id for section, text_hash, chunk_id in
                 con.execute(f"""
        SELECT c.section, c.text_hash, c.chunk_id
        FROM '{chunks}' c JOIN texts t
          ON t.section = c.section AND t.text_hash = c.text_hash
    """).fetchall()}
    con.close()
    return raw_rows, canonical


def fetch_equivalents(anchors: Iterable[Anchor], chunks: str = CHUNKS) -> list:
    """Reads the rows match_equivalents needs: every chunk in an anchor's section
    whose text contains its answer span, on any label. Which of them are the
    same drug is decided in Python, where it can be tested."""
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE spans(qid VARCHAR, section VARCHAR, span VARCHAR)")
    con.executemany("INSERT INTO spans VALUES (?, ?, ?)",
                    [(a.qid, a.section, a.answer_span) for a in anchors])
    rows = con.execute(f"""
        SELECT s.qid, c.chunk_id, c.generic_name, c.brand_name
        FROM spans s JOIN '{chunks}' c
          ON c.section = s.section AND contains(c.text, s.span)
    """).fetchall()
    con.close()
    return rows


def resolve(questions: Iterable[dict], raw: str = RAW, chunks: str = CHUNKS) -> Resolution:
    """Anchors to chunk ids, against whatever the chunker last produced."""
    questions = list(questions)
    anchors = anchors_of(questions)
    raw_rows, canonical = fetch(anchors, raw, chunks)
    strict, unresolved = match_anchors(anchors, raw_rows, canonical)
    equivalents = match_equivalents(questions, fetch_equivalents(anchors, chunks))
    relevant = {qid: ids | equivalents.get(qid, frozenset()) for qid, ids in strict.items()}
    negatives = [q["qid"] for q in questions if not q.get("anchor")]
    return Resolution(relevant, unresolved, negatives, strict)


def main() -> None:
    questions = load_gold()
    started = time.time()
    resolution = resolve(questions)
    elapsed = time.time() - started

    answerable = len(questions) - len(resolution.negatives)
    strict = sorted(len(ids) for ids in resolution.strict.values())
    wider = sorted(len(ids) for ids in resolution.relevant.values())
    gained = sum(1 for qid, ids in resolution.relevant.items()
                 if len(ids) > len(resolution.strict[qid]))
    print(f"{len(questions)} gold questions: {answerable} answerable, "
          f"{len(resolution.negatives)} negatives")
    print(f"resolved {len(resolution.relevant)} of {answerable} anchors in {elapsed:.1f}s")
    print(f"unresolved: {resolution.unresolved or 'none'}   <- must be none")
    if strict:
        print(f"strict chunks per question:       min {strict[0]}, median "
              f"{strict[len(strict) // 2]}, max {strict[-1]}")
        print(f"with other labels of the same drug: min {wider[0]}, median "
              f"{wider[len(wider) // 2]}, max {wider[-1]}")
        print(f"questions whose answer is also on other labels: {gained}")
    for split in SPLITS:
        in_split = [q for q in questions if q["split"] == split]
        negatives = sum(1 for q in in_split if q["qtype"] == "negative")
        print(f"  {split:<5} {len(in_split):>3} questions, {negatives:>2} negatives")


if __name__ == "__main__":
    main()
