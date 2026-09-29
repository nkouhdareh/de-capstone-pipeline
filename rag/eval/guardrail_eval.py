"""Phase 5, step 4: how well the refusal guardrail separates the negatives.

The gold set has 25 negatives, questions whose answer is in no label: 15 on dev,
10 on test. Two kinds: a drug with no label in the index (domperidone), and a
drug that is in the index but a question no label answers (a generic's launch
date). A good guardrail refuses them and answers everything else.

First, how well each candidate signal separates the two groups on its own:

    AUC         the chance that a random negative scores lower than a random
                answerable question: 1.0 separates perfectly, 0.5 is a coin
    cut         the highest cut that wrongly refuses at most 2 answerable
                questions, and how many negatives it then refuses

    cosine      best dense cosine similarity
    bm25 share  best BM25 score over the most the question's words could score
    unknown     minus the number of question words no chunk contains
    reranker    best cross-encoder score over hybrid-dedup's top 5
                (with --with-reranker; about 0.5 s a question)

Then the guardrail itself (rag/retrieve/guardrail.py): which negatives it
refuses, by kind, and which answerable questions it wrongly refuses.

The cuts are chosen on the split being scored, so on dev they are fitted. The
guardrail's own cut was fixed on dev; run --split test once, at the end.

Usage:
    python -m rag.eval.guardrail_eval
    python -m rag.eval.guardrail_eval --with-reranker
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence

MAX_WRONG = 2


def auc(answerable: Sequence[float], negatives: Sequence[float]) -> float:
    """Chance a negative scores below an answerable question; ties count half."""
    if not answerable or not negatives:
        return 0.0
    below = sum((n < a) + 0.5 * (n == a) for n in negatives for a in answerable)
    return below / (len(answerable) * len(negatives))


def highest_cut(answerable: Sequence[float], max_wrong: int = MAX_WRONG) -> float:
    """The highest cut such that refusing every score below it refuses at most
    max_wrong answerable questions."""
    ordered = sorted(answerable)
    return ordered[min(max_wrong, len(ordered) - 1)]


def main() -> None:
    from rag.eval.gold import load_gold
    from rag.eval.run_eval import load_retriever
    from rag.index.bm25_text import distinct, tokenize
    from rag.retrieve.guardrail import MIN_COSINE, Guardrail

    parser = argparse.ArgumentParser(description="Score the refusal guardrail.")
    parser.add_argument("--split", choices=("dev", "test"), default="dev",
                        help="dev while choosing; test once, at the end")
    parser.add_argument("--with-reranker", action="store_true",
                        help="also score the reranker's best score as a signal (slow)")
    args = parser.parse_args()

    questions = load_gold(split=args.split)
    loaded: dict = {}
    hybrid_dedup = load_retriever("hybrid-dedup", {}, loaded)
    dense, sparse = loaded["dense"], loaded["bm25"]
    guardrail = Guardrail(dense, sparse)
    reranker = None
    if args.with_reranker:
        from rag.retrieve.rerank import Reranker
        reranker = Reranker()

    rows = []
    for question in questions:
        text = question["question"]
        verdict = guardrail.check(text)
        ids = [sparse.term_id.get(term) for term in distinct(tokenize(text, sparse.stem))]
        most = sum(float(sparse.idf[i]) * (sparse.k1 + 1) for i in ids if i is not None) or 1.0
        best = sparse.search(text, 1)
        signals = {"cosine": verdict.best_cosine,
                   "bm25 share": (best[0][1] if best else 0.0) / most,
                   "unknown": -len(verdict.unknown_words)}
        if reranker:
            top5 = hybrid_dedup(question, 5)
            signals["reranker"] = max(reranker.scores(text, top5)) if top5 else float("-inf")
        rows.append((question, verdict, signals))

    negatives = [row for row in rows if row[0]["qtype"] == "negative"]
    answerable = [row for row in rows if row[0]["qtype"] != "negative"]
    print(f"\n{args.split}: {len(negatives)} negatives, {len(answerable)} answerable questions")
    print(f"\n  {'signal':<11} {'AUC':>5}   cut that wrongly refuses at most {MAX_WRONG}")
    for name in rows[0][2]:
        good = [signals[name] for _, _, signals in answerable]
        bad = [signals[name] for _, _, signals in negatives]
        cut = highest_cut(good)
        print(f"  {name:<11} {auc(good, bad):>5.3f}   {cut:>7.3f}: refuses {sum(b < cut for b in bad)} "
              f"of {len(bad)} negatives, {sum(g < cut for g in good)} of {len(good)} answerable")

    refused = Counter(q.get("negative_kind") for q, v, _ in negatives if not v.answer)
    kinds = Counter(q.get("negative_kind") for q, _, _ in negatives)
    wrong = [(q, v) for q, v, _ in answerable if not v.answer]
    right = sum(refused.values())
    print(f"\nguardrail: refuse if a word is in no chunk, or the best cosine is below {MIN_COSINE}")
    for kind, n in sorted(kinds.items()):
        print(f"  negatives refused, {kind}: {refused[kind]} of {n}")
    print(f"  answerable wrongly refused: {len(wrong)} of {len(answerable)}")
    print(f"  refusals that were right: {right} of {right + len(wrong)}")
    for q, v, _ in negatives:
        status = "refused" if not v.answer else "ANSWERED"
        detail = ", ".join(v.unknown_words) if v.unknown_words else f"cosine {v.best_cosine:.3f}"
        print(f"    {q['qid']} {status:<8} {v.reason:<14} {detail:<22} {q['question'][:60]}")
    for q, v in wrong:
        print(f"    {q['qid']} WRONGLY refused ({v.reason}, cosine {v.best_cosine:.3f}) {q['question'][:60]}")


if __name__ == "__main__":
    main()
