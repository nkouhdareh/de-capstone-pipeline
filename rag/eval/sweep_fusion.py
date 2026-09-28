"""Sweep the fusion settings on dev, each one paired against dense alone.

Both retrievers are asked once per question for their top DEPTH chunks, and
every setting fuses those same lists, so the whole sweep costs one retrieval
pass, a few seconds.

    rrf k        10, 20, 60, 100
    minmax w     dense weight 0.2 to 0.8, min-max normalised scores
    dbsf w       the same, Qdrant's distribution-based normalisation

Dev only, by construction: --split has no test choice. Trying 18 settings on
the same 68 questions and keeping the best one fits those questions, so a
setting is changed from its textbook default only if it beats the default
clearly, in a paired comparison, not because it tops this table.

Usage:
    python -m rag.eval.sweep_fusion
"""
from __future__ import annotations

import argparse
import time

from rag.eval.gold import load_gold, resolve
from rag.eval.metrics import compare, evaluate
from rag.eval.run_eval import distinct_answers
from rag.retrieve.fusion import DEPTH, fuse

K = 20
SETTINGS = ([("rrf", k) for k in (10, 20, 60, 100)]
            + [(method, w) for method in ("minmax", "dbsf") for w in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)])


def main() -> None:
    from rag.retrieve.dense import DenseRetriever
    from rag.retrieve.sparse import SparseRetriever

    parser = argparse.ArgumentParser(description="Sweep fusion settings on dev.")
    parser.add_argument("--split", choices=("dev",), default="dev", help="dev only; never test")
    args = parser.parse_args()

    questions = load_gold(split=args.split)
    resolution = resolve(questions)
    answers = distinct_answers(resolution)
    dense, sparse = DenseRetriever(), SparseRetriever()

    started = time.time()
    by_dense = {q["qid"]: dense.search(q["question"], DEPTH) for q in questions}
    by_bm25 = {q["qid"]: sparse.search(q["question"], DEPTH) for q in questions}
    print(f"{len(resolution.relevant)} answerable {args.split} questions, top {DEPTH} from each "
          f"retriever, retrieved in {time.time() - started:.1f}s")

    runs = {"dense": {qid: [c for c, _ in hits[:K]] for qid, hits in by_dense.items()},
            "bm25": {qid: [c for c, _ in hits[:K]] for qid, hits in by_bm25.items()}}
    for method, value in SETTINGS:
        name = f"rrf k={value}" if method == "rrf" else f"{method} w={value}"
        runs[name] = {qid: fuse(by_dense[qid], by_bm25[qid], method, rrf_k=value, dense_weight=value)[:K]
                      for qid in by_dense}

    print("\npaired against dense alone. * marks an interval clear of zero.")
    print(f"  {'setting':<12} {'R@5':>6} {'R@20':>6} {'MRR':>6} {'nDCG':>6}   "
          f"{'R@5 vs dense':<26} {'+/-':>5}   {'nDCG vs dense':<24}")
    for name, run in runs.items():
        scored = evaluate(run, resolution.relevant, answers=answers)
        paired = compare(runs["dense"], run, resolution.relevant, answers=answers)
        r5, nd = paired["recall@5"], paired["ndcg@10"]
        print(f"  {name:<12} {scored['recall@5'].value:>6.3f} {scored['recall@20'].value:>6.3f} "
              f"{scored['mrr@10'].value:>6.3f} {scored['ndcg@10'].value:>6.3f}   "
              f"{r5.diff:+.3f} [{r5.low:+.3f}, {r5.high:+.3f}]{'*' if r5.low > 0 else ' '}  "
              f"{r5.better:>2}/{r5.worse:<2}   "
              f"{nd.diff:+.3f} [{nd.low:+.3f}, {nd.high:+.3f}]{'*' if nd.low > 0 else ' '}")
    print("  +/-: questions where the setting did better / worse than dense at recall@5")


if __name__ == "__main__":
    main()
