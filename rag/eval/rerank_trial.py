"""Phase 5, step 3: does a cross-encoder reranker earn its cost? Dev only.

For each depth, hybrid's top `depth` candidates (before any collapsing) are
scored by the reranker, reordered, and only then are near-copies collapsed:
collapsing first would throw away answers the reranker could have lifted
(step 2 found 8 such questions). Every row is paired against hybrid-dedup, the
pipeline without a reranker, and the reranker's time per question is printed
beside it. The reranker is slow on a CPU, about 100 ms per chunk, so this run
takes about 10 minutes with the default depths.

Usage:
    python -m rag.eval.rerank_trial                  # depths 20 and 50
    python -m rag.eval.rerank_trial --depths 20 30 50 100
"""
from __future__ import annotations

import argparse
import time

K = 20


def main() -> None:
    from rag.eval.ann_recall import percentile
    from rag.eval.gold import load_gold, resolve
    from rag.eval.metrics import compare, evaluate
    from rag.eval.run_eval import distinct_answers, load_retriever
    from rag.retrieve.fusion import COLLAPSE_ABOVE, collapse_near_copies
    from rag.retrieve.rerank import Reranker

    parser = argparse.ArgumentParser(description="Measure the reranker against hybrid-dedup on dev.")
    parser.add_argument("--depths", type=int, nargs="+", default=[20, 50],
                        help="how many hybrid candidates the reranker scores")
    args = parser.parse_args()

    questions = load_gold(split="dev")
    resolution = resolve(questions)
    answers = distinct_answers(resolution)
    loaded: dict = {}
    hybrid = load_retriever("hybrid", {}, loaded)
    hybrid_dedup = load_retriever("hybrid-dedup", {}, loaded)
    dense = loaded["dense"]
    reranker = Reranker()

    def collapsed(chunk_ids):
        vectors = dense.vectors_of(chunk_ids)
        cosine = vectors @ vectors.T
        kept = collapse_near_copies(len(chunk_ids), lambda i, j: float(cosine[i, j]), COLLAPSE_ABOVE, K)
        return [chunk_ids[i] for i in kept]

    candidates = {q["qid"]: hybrid(q, max(args.depths)) for q in questions}
    baseline = {q["qid"]: hybrid_dedup(q, K) for q in questions}
    reranker.texts.fetch(sorted({c for ids in candidates.values() for c in ids}))

    scored = evaluate(baseline, resolution.relevant, answers=answers)
    print(f"\n{len(resolution.relevant)} answerable dev questions; hybrid-dedup: recall@5 "
          f"{scored['recall@5'].value:.3f}, MRR@10 {scored['mrr@10'].value:.3f}")
    print(f"  {'depth':>5}  {'p50 s':>6}  {'R@5':>5}  {'MRR':>5}   {'R@5 vs hybrid-dedup':<27} {'+/-':>5}"
          f"   {'MRR vs hybrid-dedup':<24}")
    for depth in args.depths:
        reranked, seconds = {}, []
        for question in questions:
            pool = candidates[question["qid"]][:depth]
            started = time.perf_counter()
            order = [chunk_id for chunk_id, _ in reranker.rerank(question["question"], pool)]
            seconds.append(time.perf_counter() - started)
            reranked[question["qid"]] = collapsed(order)
        run = evaluate(reranked, resolution.relevant, answers=answers)
        paired = compare(baseline, reranked, resolution.relevant, answers=answers)
        r5, mrr = paired["recall@5"], paired["mrr@10"]
        print(f"  {depth:>5}  {percentile(seconds, 50):>6.1f}  {run['recall@5'].value:>5.3f}  "
              f"{run['mrr@10'].value:>5.3f}   {r5.diff:+.3f} [{r5.low:+.3f}, {r5.high:+.3f}]  "
              f"{r5.better:>2}/{r5.worse:<2}   {mrr.diff:+.3f} [{mrr.low:+.3f}, {mrr.high:+.3f}]", flush=True)
    print("  +/-: questions where reranking did better / worse at recall@5")


if __name__ == "__main__":
    main()
