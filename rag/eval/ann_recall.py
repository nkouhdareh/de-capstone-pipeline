"""Phase 4, step 5: approximate search measured against exact search (ADR-016).

dense.py searches exactly: every question is compared with all 360,916 vectors.
An approximate nearest neighbour (ANN) index skips most of them to go faster,
and may miss some of the true closest chunks. This measures how many, and how
much time it saves, so the store decision rests on numbers.

The ANN index is faiss HNSW (Meta, MIT): a graph in which each vector links to
its M nearest neighbours, walked from the top at query time. HNSW is what
Qdrant, pgvector and LanceDB use as well, so the trade-off measured here is the
one any of them would bring.

    M               links per vector: memory and build time (32 here)
    efConstruction  how hard the build looks for good links (200 here)
    efSearch        how many candidates a query keeps while walking: the
                    runtime dial between speed and recall

ANN recall@20 is the share of exact search's top 20 that HNSW also returns.
Then the part that matters: hybrid retrieval with HNSW in place of exact dense
search, paired against the real hybrid on the gold set.

The index is built in memory, about a minute, and nothing is written. Dev
questions only. faiss is needed for this script alone: nothing in the retrieval
path imports it.

Usage:
    python -m rag.eval.ann_recall
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from math import ceil

M = 32
EF_CONSTRUCTION = 200
EF_SEARCH = (16, 32, 64, 128, 256)
EF_HYBRID = 128
K = 20
THREADS = 8


def overlap(exact: Iterable, approximate: Iterable, k: int = K) -> float:
    """Share of the exact top k that the approximate search also returned."""
    return len(set(exact) & set(approximate)) / k


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile: the smallest value with at least p% at or below it."""
    ordered = sorted(values)
    return ordered[max(0, ceil(p / 100 * len(ordered)) - 1)]


def main() -> None:
    try:
        import faiss
    except ImportError:
        raise SystemExit("faiss is not installed: python -m pip install faiss-cpu==1.15.1") from None
    import numpy as np

    from rag.eval.gold import load_gold, resolve
    from rag.eval.metrics import compare, format_comparison
    from rag.eval.run_eval import distinct_answers
    from rag.retrieve.dense import DenseRetriever, top_k
    from rag.retrieve.fusion import DEPTH, fuse
    from rag.retrieve.sparse import SparseRetriever

    questions = load_gold(split="dev")
    dense = DenseRetriever()
    vectors = np.ascontiguousarray(dense.vectors)

    started = time.perf_counter()
    queries = np.stack([dense.embed_query(q["question"]) for q in questions])
    embed_ms = (time.perf_counter() - started) * 1000 / len(questions)
    exact, exact_ms = [], []
    for query in queries:
        started = time.perf_counter()
        exact.append(top_k(vectors @ query, K).tolist())
        exact_ms.append((time.perf_counter() - started) * 1000)
    print(f"{len(questions)} dev questions, {len(dense.ids):,} vectors of {vectors.shape[1]}")
    print(f"embedding a question: {embed_ms:.1f} ms on average")
    print(f"exact search: p50 {percentile(exact_ms, 50):.1f} ms, p95 {percentile(exact_ms, 95):.1f} ms, "
          f"recall 1.000 by definition")

    faiss.omp_set_num_threads(THREADS)
    started = time.perf_counter()
    index = faiss.IndexHNSWFlat(vectors.shape[1], M, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = EF_CONSTRUCTION
    index.add(vectors)
    size = len(faiss.serialize_index(index)) / 1e6
    print(f"\nHNSW M={M}, efConstruction={EF_CONSTRUCTION}: built in {time.perf_counter() - started:.0f}s, "
          f"{size:.0f} MB (the vectors alone are {vectors.nbytes / 1e6:.0f} MB)")
    faiss.omp_set_num_threads(1)      # one question at a time, as the app will ask them
    print(f"  {'efSearch':>8}  {'recall@20':>9}  {'worst':>5}  {'p50 ms':>6}  {'p95 ms':>6}")
    for ef in EF_SEARCH:
        index.hnsw.efSearch = ef
        found, ms = [], []
        for query, truth in zip(queries, exact):
            started = time.perf_counter()
            _, ids = index.search(query[None, :], K)
            ms.append((time.perf_counter() - started) * 1000)
            found.append(overlap(truth, ids[0].tolist()))
        print(f"  {ef:>8}  {sum(found) / len(found):>9.3f}  {min(found):>5.2f}  "
              f"{percentile(ms, 50):>6.2f}  {percentile(ms, 95):>6.2f}")

    resolution = resolve(questions)
    sparse = SparseRetriever()
    index.hnsw.efSearch = EF_HYBRID
    with_exact, with_hnsw = {}, {}
    for question, query in zip(questions, queries):
        by_bm25 = sparse.search(question["question"], DEPTH)
        scores, ids = index.search(query[None, :], DEPTH)
        approximate = [(dense.ids[i], float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
        with_exact[question["qid"]] = fuse(dense.search(question["question"], DEPTH), by_bm25)[:K]
        with_hnsw[question["qid"]] = fuse(approximate, by_bm25)[:K]
    print()
    print(format_comparison(compare(with_exact, with_hnsw, resolution.relevant,
                                    answers=distinct_answers(resolution)),
                            "hybrid", f"hybrid-hnsw-ef{EF_HYBRID}"))


if __name__ == "__main__":
    main()
