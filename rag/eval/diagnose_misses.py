"""Where a retriever's top-5 misses come from, on dev.

Before fixing a ranking, sort its failures. For every answerable dev question
the retriever is asked for its top 100, and the first chunk that answers the
question is found:

    top 5          a hit, nothing to fix
    rank 6-20      found but ranked too low: a reranker or diversity can fix it
    rank 21-100    found, deep: only a reranker over many candidates can reach it
    not in top 100 not retrieved at all: no reordering can fix it

It also counts near-copies: top-5 places whose chunk has cosine similarity above
COLLAPSE_ABOVE with a chunk ranked above it. Five places holding one paragraph
are one piece of evidence.

Usage:
    python -m rag.eval.diagnose_misses                       # hybrid
    python -m rag.eval.diagnose_misses --retriever hybrid-dedup
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterable, Sequence

from rag.retrieve.fusion import COLLAPSE_ABOVE

DEPTH = 100
CLASSES = ("top 5", "rank 6-20", "rank 21-100", "not in top 100")


def first_hit(ranked: Sequence[str], relevant: Iterable[str]) -> int | None:
    """Rank, from 1, of the first chunk that answers; None if none does."""
    answers = set(relevant)
    return next((rank for rank, chunk_id in enumerate(ranked, start=1) if chunk_id in answers), None)


def miss_class(rank: int | None) -> str:
    if rank is None:
        return CLASSES[3]
    return CLASSES[0] if rank <= 5 else CLASSES[1] if rank <= 20 else CLASSES[2]


def near_copies(n: int, similarity: Callable[[int, int], float], threshold: float = COLLAPSE_ABOVE) -> int:
    """How many of positions 0 to n-1 are near-copies of a position above them."""
    return sum(any(similarity(i, j) > threshold for j in range(i)) for i in range(n))


def main() -> None:
    from rag.eval.gold import load_gold, resolve
    from rag.eval.run_eval import RETRIEVERS, load_retriever

    parser = argparse.ArgumentParser(description="Sort a retriever's top-5 misses on dev.")
    parser.add_argument("--retriever", choices=[r for r in RETRIEVERS if r.startswith("hybrid")],
                        default="hybrid")
    args = parser.parse_args()

    questions = load_gold(split="dev")
    resolution = resolve(questions)
    loaded: dict = {}
    retriever = load_retriever(args.retriever, {}, loaded)
    dense = loaded["dense"]

    classes, copies, slots = Counter(), 0, 0
    misses = []
    for question in questions:
        relevant = resolution.relevant.get(question["qid"])
        if not relevant:
            continue
        ranked = retriever(question, DEPTH)
        rank = first_hit(ranked, relevant)
        classes[miss_class(rank)] += 1
        vectors = dense.vectors_of(ranked[:5])
        cosine = vectors @ vectors.T
        copies += near_copies(len(ranked[:5]), lambda i, j, c=cosine: float(c[i, j]))
        slots += len(ranked[:5])
        if miss_class(rank) != CLASSES[0]:
            misses.append((question["qid"], question["qtype"], rank, question["question"]))

    print(f"\n{args.retriever} on {sum(classes.values())} answerable dev questions")
    for name in CLASSES:
        print(f"  {name:<15} {classes[name]:>3}")
    print(f"  near-copies in the top 5: {copies} of {slots} places ({copies / slots:.0%}), "
          f"cosine above {COLLAPSE_ABOVE}")
    print("\nmisses:")
    for qid, qtype, rank, text in misses:
        print(f"  {qid} {qtype:<10} first answer at {rank if rank else '-':>3}  {text[:70]}")


if __name__ == "__main__":
    main()
