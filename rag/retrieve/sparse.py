"""Phase 4: BM25 keyword retrieval over the same 360,916 chunks as the dense index.

Hand-rolled on numpy, so the mechanism can be explained rather than trusted.
bm25_text.py holds the rules (what is read, the tokenizer, the formula) and the
plain-Python reference this code is tested against.

The index is an inverted index: for every term, the chunks that contain it and
how often. Stored term by term, so answering a question touches only the rows of
its own few terms, never the whole corpus:

    terms.txt         term i on line i
    indptr.npy        term i's postings are rows indptr[i] to indptr[i+1]
    postings_doc.npy  int32, the chunk (row in chunk_ids.txt) of each posting
    postings_tf.npy   uint16, how often the term is in that chunk
    doc_len.npy       int32, each chunk's length in terms
    chunk_ids.txt     the chunk id of each row
    manifest.json     what produced it

Raw counts are stored, not finished weights, so k1 and b are query-time
settings: tuning them needs no rebuild.

Every distinct raw word is stemmed once, not every time it appears. Measured on
the full build: 57 million words once stopwords are gone, but only 57,806
distinct stems. The whole build takes about half a minute.

Usage:
    python -m rag.retrieve.sparse --build --limit 2000 --out <folder>   # smoke test
    python -m rag.retrieve.sparse --build                                # the full index
"""
from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from rag.index.bm25_text import (
    K1,
    STOPWORDS,
    TEXT_VERSION,
    TOKEN,
    B,
    bm25_text,
    distinct,
    english_stemmer,
    tokenize,
)
from rag.retrieve.dense import top_k

RAGDATA = Path("D:/capstone/data/rag")
CHUNKS = RAGDATA / "chunks.parquet"
INDEX = RAGDATA / "index" / "bm25-v1"
STEMMER = "snowball-english"
BATCH = 10_000


class TermIds(dict):
    """Raw word -> term id, or -1 for a stopword. A word is stemmed the first
    time it is seen and remembered after that. Gives the same terms as
    tokenize(), which the tests check."""

    def __init__(self, stem=None):
        super().__init__()
        self.stem = stem
        self.terms: dict[str, int] = {}

    def __missing__(self, raw: str) -> int:
        if raw in STOPWORDS:
            term_id = -1
        else:
            term = self.stem(raw) if self.stem else raw
            term_id = self.terms.setdefault(term, len(self.terms))
        self[raw] = term_id
        return term_id


def build_postings(rows: Iterable[tuple], stem=None, progress: bool = False) -> dict:
    """rows: (chunk_id, text, generic_name, brand_name, section). Returns the
    arrays and lists that make up the index, in memory."""
    ids = TermIds(stem)
    chunk_ids, lengths, terms, docs, tfs = [], [], [], [], []
    started = time.time()
    for row, (chunk_id, text, generic, brand, section) in enumerate(rows):
        words = TOKEN.findall(bm25_text(text, generic, brand, section).lower())
        term_ids = np.fromiter((ids[word] for word in words), dtype=np.int32, count=len(words))
        term_ids = term_ids[term_ids >= 0]
        unique, counts = np.unique(term_ids, return_counts=True)
        chunk_ids.append(chunk_id)
        lengths.append(len(term_ids))
        terms.append(unique)
        tfs.append(counts)
        docs.append(np.full(len(unique), row, dtype=np.int32))
        if progress and (row + 1) % 50_000 == 0:
            print(f"  {row + 1:,} chunks, {len(ids.terms):,} terms, {time.time() - started:.0f}s")

    term_of = np.concatenate(terms) if terms else np.empty(0, dtype=np.int32)
    tf = np.concatenate(tfs) if tfs else np.empty(0, dtype=np.int64)
    if tf.size and tf.max() > np.iinfo(np.uint16).max:
        raise ValueError(f"a term repeats {tf.max()} times in one chunk, too many for uint16")
    order = np.argsort(term_of, kind="stable")      # term by term; chunks stay in order
    indptr = np.zeros(len(ids.terms) + 1, dtype=np.int64)
    indptr[1:] = np.cumsum(np.bincount(term_of, minlength=len(ids.terms)))
    return {
        "terms": list(ids.terms),
        "chunk_ids": chunk_ids,
        "indptr": indptr,
        "postings_doc": (np.concatenate(docs) if docs else np.empty(0, dtype=np.int32))[order],
        "postings_tf": tf[order].astype(np.uint16),
        "doc_len": np.asarray(lengths, dtype=np.int32),
    }


def save(index: Mapping, out_dir: Path, manifest: Mapping) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("indptr", "postings_doc", "postings_tf", "doc_len"):
        np.save(out_dir / f"{name}.npy", index[name])
    (out_dir / "terms.txt").write_text("\n".join(index["terms"]) + "\n", encoding="utf-8")
    (out_dir / "chunk_ids.txt").write_text("\n".join(index["chunk_ids"]) + "\n", encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


class SparseRetriever:
    def __init__(self, index_dir: Path = INDEX, stem=None, k1: float = K1, b: float = B):
        index_dir = Path(index_dir)
        self.manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("text") != TEXT_VERSION:
            raise ValueError(f"{index_dir} was built with text rules {self.manifest.get('text')!r}, "
                             f"this code reads {TEXT_VERSION!r}")
        if stem is None and self.manifest.get("stemmer") == STEMMER:
            stem = english_stemmer()
        self.stem = stem
        self.terms = (index_dir / "terms.txt").read_text(encoding="utf-8").split()
        self.term_id = {term: i for i, term in enumerate(self.terms)}
        self.ids = (index_dir / "chunk_ids.txt").read_text(encoding="utf-8").split()
        self.indptr = np.load(index_dir / "indptr.npy")
        self.postings_doc = np.load(index_dir / "postings_doc.npy")
        self.postings_tf = np.load(index_dir / "postings_tf.npy")
        doc_len = np.load(index_dir / "doc_len.npy").astype(np.float32)
        if len(self.ids) != len(doc_len) or len(self.terms) + 1 != len(self.indptr):
            raise ValueError(f"{index_dir} is inconsistent: its files disagree on sizes")

        n_docs = len(self.ids)
        df = np.diff(self.indptr).astype(np.float64)
        self.idf = np.log1p((n_docs - df + 0.5) / (df + 0.5)).astype(np.float32)
        self.k1 = k1
        # The length part of the formula depends only on the chunk, so it is done once.
        self.norm = (k1 * (1 - b + b * doc_len / max(float(doc_len.mean()), 1.0))).astype(np.float32)

    def scores(self, question: str) -> np.ndarray:
        """Every chunk's BM25 score for the question; zero where no term matches."""
        scores = np.zeros(len(self.ids), dtype=np.float32)
        for term in distinct(tokenize(question, self.stem)):
            t = self.term_id.get(term)
            if t is None:
                continue
            lo, hi = self.indptr[t], self.indptr[t + 1]
            docs = self.postings_doc[lo:hi]
            tf = self.postings_tf[lo:hi].astype(np.float32)
            scores[docs] += self.idf[t] * tf * (self.k1 + 1) / (tf + self.norm[docs])
        return scores

    def search(self, question: str, k: int = 20) -> list[tuple[str, float]]:
        """The k best chunks, best first, as (chunk_id, score). Chunks sharing no
        term with the question are never returned, so fewer than k can come back."""
        scores = self.scores(question)
        return [(self.ids[i], float(scores[i])) for i in top_k(scores, k) if scores[i] > 0]

    def __call__(self, question: Mapping, k: int) -> list[str]:
        """The retriever interface run_eval expects: a gold record in, chunk ids out."""
        return [chunk_id for chunk_id, _ in self.search(question["question"], k)]


def read_chunks(chunks: Path, limit: int):
    """Chunks in chunk_id order, streamed in batches so the texts are never all in
    memory at once. With --limit, the first `limit` of them."""
    import duckdb
    sql = (f"SELECT chunk_id, text, generic_name, brand_name, section "
           f"FROM '{chunks.as_posix()}' ORDER BY chunk_id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    result = duckdb.execute(sql)
    while batch := result.fetchmany(BATCH):
        yield from batch


def main() -> None:
    from rag.index.build_index import git_commit, sha256

    parser = argparse.ArgumentParser(description="Build the BM25 index.")
    parser.add_argument("--build", action="store_true", help="build the index")
    parser.add_argument("--limit", type=int, default=0, help="only the first N chunks, for a smoke test")
    parser.add_argument("--out", type=Path, default=INDEX, help="index folder")
    args = parser.parse_args()
    if not args.build:
        parser.error("nothing to do: pass --build")
    if (args.out / "manifest.json").exists():
        raise SystemExit(f"{args.out} already holds an index; delete it first to rebuild")

    started = time.time()
    print(f"building {args.out} from {CHUNKS}" + (f", first {args.limit:,} chunks" if args.limit else ""))
    index = build_postings(read_chunks(CHUNKS, args.limit), english_stemmer(), progress=True)
    seconds = time.time() - started
    manifest = {
        "index": args.out.name,
        "text": TEXT_VERSION,
        "stemmer": STEMMER,
        "stopwords": f"lucene-english-{len(STOPWORDS)}",
        "chunks_file": CHUNKS.as_posix(),
        "chunks_sha256": sha256(CHUNKS),
        "limit": args.limit,
        "n_chunks": len(index["chunk_ids"]),
        "n_terms": len(index["terms"]),
        "n_postings": len(index["postings_doc"]),
        "avg_len": round(float(index["doc_len"].mean()), 1) if len(index["doc_len"]) else 0.0,
        "build_seconds": round(seconds),
        "git_commit": git_commit(),
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save(index, args.out, manifest)
    size = sum(path.stat().st_size for path in args.out.iterdir()) / 1e6
    print(f"done in {seconds:.0f}s: {manifest['n_chunks']:,} chunks, {manifest['n_terms']:,} terms, "
          f"{manifest['n_postings']:,} postings, {size:.0f} MB in {args.out}")


if __name__ == "__main__":
    main()
