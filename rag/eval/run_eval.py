"""Phase 2 gate: score a retriever on the gold set and print the table.

Two baselines ship with it, and they are not decoration. A harness that has
never been shown to produce 1.000 for a retriever that cannot be wrong, and
~0.000 for one that cannot be right, is a harness whose numbers mean nothing.
Every later claim in this project rests on these two lines.

    perfect  returns exactly the chunks the gold set says answer the question
    random   returns chunk ids drawn from the 360,916 in the index

A retriever is any callable (question, k) -> chunk ids, best first. The question
is the whole gold record, so a real retriever reads question["question"] while
the perfect baseline reads question["qid"]. Phase 3 drops a dense retriever into
the same slot without touching this file.

Report on dev while tuning. Run --split test once, at the end, and publish that.

Usage:
    python -m rag.eval.run_eval                  # both baselines on dev
    python -m rag.eval.run_eval --split test     # the held-out split
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence

from rag.eval.gold import CHUNKS, Resolution, load_gold, resolve
from rag.eval.metrics import KS, evaluate, format_table

BUDGET_SECONDS = 60     # the Phase 2 gate: a slow harness stops being run
RANDOM_SEED = 20260924
RANDOM_CEILING = 0.05   # a random retriever above this means the gold set leaks

Retriever = Callable[[Mapping, int], Sequence[str]]


def perfect_retriever(resolution: Resolution) -> Retriever:
    """Cannot be wrong. Any score below 1.000 is a bug in the harness."""
    def search(question: Mapping, k: int) -> list[str]:
        return sorted(resolution.relevant.get(question["qid"], ()))[:k]
    return search


def random_retriever(chunk_ids: Sequence[str], seed: int = RANDOM_SEED) -> Retriever:
    """Cannot be right. With 20 draws from 360,916 chunks, the chance of a hit
    is about 1 in 18,000, so anything above noise means the answers leaked."""
    rng = random.Random(seed)
    population = list(chunk_ids)          # copied once, not once per question

    def search(question: Mapping, k: int) -> list[str]:
        return rng.sample(population, k)
    return search


def all_chunk_ids(chunks: str = CHUNKS) -> list[str]:
    import duckdb
    return [row[0] for row in duckdb.execute(f"SELECT chunk_id FROM '{chunks}'").fetchall()]


def run_retriever(questions: Sequence[Mapping], retriever: Retriever, k: int) -> dict:
    return {question["qid"]: list(retriever(question, k)) for question in questions}


def recall_by_qtype(run: Mapping, relevant: Mapping, questions: Sequence[Mapping],
                    k: int = 5) -> list[tuple]:
    """Where a retriever fails matters as much as how often. Paraphrase questions
    are the dense half's job, identifier questions are BM25's."""
    rows = []
    for qtype in sorted({q["qtype"] for q in questions if q["qid"] in relevant}):
        qids = [q["qid"] for q in questions if q["qtype"] == qtype and q["qid"] in relevant]
        scored = evaluate({qid: run.get(qid, []) for qid in qids},
                          {qid: relevant[qid] for qid in qids}, ks=(k,))
        rows.append((qtype, scored[f"recall@{k}"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Score retrievers on the gold set.")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev",
                        help="dev while tuning; test once, at the end")
    parser.add_argument("--k", type=int, default=max(KS), help="how deep to retrieve")
    args = parser.parse_args()

    started = time.time()
    questions = load_gold(split=None if args.split == "all" else args.split)
    resolution = resolve(questions)
    relevant = resolution.relevant
    negatives = len(resolution.negatives)

    print(f"gold set: {len(questions)} questions in '{args.split}', "
          f"{len(relevant)} answerable, {negatives} negatives")
    if resolution.unresolved:
        print(f"  WARNING: {len(resolution.unresolved)} anchors did not resolve: "
              f"{resolution.unresolved}")

    baselines = {
        "perfect": perfect_retriever(resolution),
        "random": random_retriever(all_chunk_ids()),
    }
    scores = {}
    for name, retriever in baselines.items():
        run = run_retriever(questions, retriever, args.k)
        scores[name] = evaluate(run, relevant)
        print()
        print(format_table(scores[name], f"{args.split}, {name} retriever"))
        if name == "perfect":
            print("  recall@5 by question type")
            for qtype, metric in recall_by_qtype(run, relevant, questions):
                print(f"    {qtype:<12} {metric.value:>6.3f}   n={metric.n}")

    elapsed = time.time() - started
    checks = [
        ("perfect retriever scores 1.000 everywhere",
         all(m.value == 1.0 for m in scores["perfect"].values())),
        (f"random retriever stays under {RANDOM_CEILING}",
         all(m.value < RANDOM_CEILING for m in scores["random"].values())),
        (f"whole run under {BUDGET_SECONDS}s (took {elapsed:.1f}s)",
         elapsed < BUDGET_SECONDS),
    ]
    print()
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    if not all(passed for _, passed in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
