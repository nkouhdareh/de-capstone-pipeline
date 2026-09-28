"""Score a retriever on the gold set and print the table.

Two baselines ship with it, and they are not decoration. A harness that has
never been shown to produce 1.000 for a retriever that cannot be wrong, and
~0.000 for one that cannot be right, is a harness whose numbers mean nothing.
Every later claim in this project rests on these two lines.

    baselines        perfect returns exactly the chunks the gold set says answer
                     the question; random returns chunk ids drawn from the index
    dense            arctic-embed-s, exact search over all 360,916 chunks
    dense-noprefix   the same without arctic's query instruction, so what the
                     prefix is worth gets measured instead of assumed

A retriever is any callable (question, k) -> chunk ids, best first. The question
is the whole gold record, so a real retriever reads question["question"] while
the perfect baseline reads question["qid"].

A chunk counts as correct when it holds the question's answer text, in the same
section, for the same drug, on any label: gold.py explains why the first dense
run forced that. nDCG counts each distinct answer once, so copies of one
paragraph earn nothing extra. The strict score, the question's own label only,
is printed beside the rest.

Report on dev while tuning. Run --split test once, at the end, and publish that.

Usage:
    python -m rag.eval.run_eval                          # the two baselines, on dev
    python -m rag.eval.run_eval --retriever dense        # the dense index, on dev
    python -m rag.eval.run_eval --retriever dense --split test    # once, at the end
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

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


def distinct_answers(resolution: Resolution) -> dict:
    """How many distinct answers each question has, for nDCG: its strict chunks.
    The same text on other labels adds copies, not answers."""
    return {qid: len(ids) for qid, ids in resolution.strict.items()}


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


def print_by_qtype(run: Mapping, relevant: Mapping, questions: Sequence[Mapping]) -> None:
    print("  recall@5 by question type")
    for qtype, metric in recall_by_qtype(run, relevant, questions):
        print(f"    {qtype:<12} {metric.value:>6.3f}   n={metric.n}")


def run_baselines(questions: Sequence[Mapping], resolution: Resolution, split: str,
                  k: int) -> list[tuple[str, bool]]:
    baselines = {
        "perfect": perfect_retriever(resolution),
        "random": random_retriever(all_chunk_ids()),
    }
    scores = {}
    for name, retriever in baselines.items():
        run = run_retriever(questions, retriever, k)
        scores[name] = evaluate(run, resolution.relevant, answers=distinct_answers(resolution))
        print()
        print(format_table(scores[name], f"{split}, {name} retriever"))
        if name == "perfect":
            print_by_qtype(run, resolution.relevant, questions)
    return [
        ("perfect retriever scores 1.000 everywhere",
         all(m.value == 1.0 for m in scores["perfect"].values())),
        (f"random retriever stays under {RANDOM_CEILING}",
         all(m.value < RANDOM_CEILING for m in scores["random"].values())),
    ]


def run_dense(questions: Sequence[Mapping], resolution: Resolution, split: str, k: int,
              index: Path | None, use_prefix: bool) -> list[tuple[str, bool]]:
    from rag.retrieve.dense import INDEX, DenseRetriever

    loaded = time.time()
    retriever = DenseRetriever(index or INDEX, use_prefix=use_prefix)
    manifest = retriever.manifest
    print(f"index: {manifest['index']}, {len(retriever.ids):,} chunks, {manifest['precision']}, "
          f"query prefix {'on' if use_prefix else 'OFF'}, loaded in {time.time() - loaded:.1f}s")

    searched = time.time()
    run = run_retriever(questions, retriever, k)
    per_question = (time.time() - searched) / max(1, len(questions))
    scored = evaluate(run, resolution.relevant, answers=distinct_answers(resolution))
    strict = evaluate(run, resolution.strict, ks=(5,))["recall@5"]
    print()
    print(format_table(scored, f"{split}, {'dense' if use_prefix else 'dense-noprefix'} retriever"))
    print(f"  strict, own label only: recall@5 {strict.value:.3f} [{strict.low:.3f}, {strict.high:.3f}]")
    print_by_qtype(run, resolution.relevant, questions)

    # The Phase 3 gate: this one number decides whether Phase 5's reranker is worth building.
    gap = scored["recall@20"].value - scored["recall@5"].value
    print(f"\n  recall@20 minus recall@5: {gap:+.3f}   ({1000 * per_question:.0f} ms per question)")
    print("    large: the answer is retrieved but ranked too low, which a reranker can fix")
    print("    small: the answer is not retrieved at all, which no reranker can fix")
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Score retrievers on the gold set.")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev",
                        help="dev while tuning; test once, at the end")
    parser.add_argument("--k", type=int, default=max(KS), help="how deep to retrieve")
    parser.add_argument("--retriever", choices=("baselines", "dense", "dense-noprefix"),
                        default="baselines",
                        help="baselines proves the harness works; dense scores the Phase 3 index")
    parser.add_argument("--index", type=Path,
                        help="index folder for dense; default the full arctic-s-fp32 index")
    args = parser.parse_args()

    started = time.time()
    questions = load_gold(split=None if args.split == "all" else args.split)
    resolution = resolve(questions)
    print(f"gold set: {len(questions)} questions in '{args.split}', "
          f"{len(resolution.relevant)} answerable, {len(resolution.negatives)} negatives")
    if resolution.unresolved:
        print(f"  WARNING: {len(resolution.unresolved)} anchors did not resolve: "
              f"{resolution.unresolved}")

    if args.retriever == "baselines":
        checks = run_baselines(questions, resolution, args.split, args.k)
    else:
        checks = run_dense(questions, resolution, args.split, args.k, args.index,
                           use_prefix=args.retriever == "dense")

    elapsed = time.time() - started
    checks.append((f"whole run under {BUDGET_SECONDS}s (took {elapsed:.1f}s)",
                   elapsed < BUDGET_SECONDS))
    print()
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    if not all(passed for _, passed in checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
