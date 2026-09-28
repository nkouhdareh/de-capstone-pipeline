"""Phase 4, step 4: the most a drug-name filter could add to hybrid retrieval.

TR-53 asks for a query-time filter: find the drug a question names, search only
that drug's chunks, and fall back to the unfiltered search when the filter
leaves too little. Before building a detector, this measures its ceiling with
a perfect one: the gold set's own drug and brand fields, which a real system
never sees. It is an ORACLE, a measurement, never a retriever.

A chunk passes the oracle when it is the question's drug by the rule gold.py
already uses: the same significant name words in the generic name, or in the
brand name for identifier questions. The filtered hybrid is the same RRF over
the top 100 of each retriever, restricted to those chunks, and topped up from
the unfiltered hybrid when fewer than k chunks pass.

Two numbers come out:
    how many of hybrid's top 5 are already the right drug
    oracle-filtered hybrid against plain hybrid, paired, on dev

If even a perfect detector gains little, a real one, which must be tuned on
the same 83 dev questions, is not worth its risk here.

Usage:
    python -m rag.eval.filter_ceiling
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from rag.eval.gold import CHUNKS, drug_tokens


def index_names(rows: Iterable[tuple]) -> tuple[dict, dict]:
    """rows: (chunk_id, generic_name, brand_name). Chunk ids by the significant
    words of their generic name, and of their brand name. Built once, so each
    question is a dictionary lookup rather than a pass over 360,916 names."""
    by_generic, by_brand = defaultdict(list), defaultdict(list)
    for chunk_id, generic, brand in rows:
        by_generic[drug_tokens(generic)].append(chunk_id)
        by_brand[drug_tokens(brand)].append(chunk_id)
    return by_generic, by_brand


def oracle_allowed(question: Mapping, by_generic: Mapping, by_brand: Mapping) -> list[str]:
    """The chunks of the question's drug, by the rule gold.py already uses: the
    same significant words in the generic name, or in the brand name for
    identifier questions. A name with no significant words, such as ZINC SULFATE
    once salts are ignored, matches nothing: the oracle cannot name that drug."""
    if question["qtype"] == "identifier":
        want, index = drug_tokens(question.get("brand")), by_brand
    else:
        want, index = drug_tokens(question.get("drug")), by_generic
    return list(index.get(want, ())) if want else []


def top_up(filtered: Sequence[str], fallback: Iterable[str], k: int) -> list[str]:
    """The filtered ranking first, then the unfiltered one, without repeats, to k."""
    ranked = list(filtered[:k])
    seen = set(ranked)
    for chunk_id in fallback:
        if len(ranked) >= k:
            break
        if chunk_id not in seen:
            ranked.append(chunk_id)
            seen.add(chunk_id)
    return ranked


def main() -> None:
    import duckdb
    import numpy as np

    from rag.eval.gold import load_gold, resolve
    from rag.eval.metrics import compare, format_comparison
    from rag.eval.run_eval import distinct_answers
    from rag.retrieve.dense import DenseRetriever, top_k
    from rag.retrieve.fusion import DEPTH, fuse
    from rag.retrieve.sparse import SparseRetriever

    k = 20
    questions = load_gold(split="dev")
    resolution = resolve(questions)
    answers = distinct_answers(resolution)
    by_generic, by_brand = index_names(duckdb.execute(
        f"SELECT chunk_id, generic_name, brand_name FROM '{CHUNKS}' ORDER BY chunk_id").fetchall())
    dense, sparse = DenseRetriever(), SparseRetriever()
    dense_row = {chunk_id: i for i, chunk_id in enumerate(dense.ids)}
    sparse_row = {chunk_id: i for i, chunk_id in enumerate(sparse.ids)}

    hybrid, oracle = {}, {}
    top5 = right = unnamed = 0
    for question in questions:
        qid, text = question["qid"], question["question"]
        hybrid[qid] = fuse(dense.search(text, DEPTH), sparse.search(text, DEPTH))[:k]
        if qid not in resolution.relevant:
            continue                                   # negatives are not scored here
        allowed = oracle_allowed(question, by_generic, by_brand)
        top5 += 5
        right += len(set(hybrid[qid][:5]) & set(allowed))
        if not allowed:
            unnamed += 1
            oracle[qid] = hybrid[qid]
            continue
        cosine = dense.vectors[np.array([dense_row[c] for c in allowed])] @ dense.embed_query(text)
        by_dense = [(allowed[i], float(cosine[i])) for i in top_k(cosine, DEPTH)]
        bm25 = sparse.scores(text)[np.array([sparse_row[c] for c in allowed])]
        by_bm25 = [(allowed[i], float(bm25[i])) for i in top_k(bm25, DEPTH) if bm25[i] > 0]
        oracle[qid] = top_up(fuse(by_dense, by_bm25), hybrid[qid], k)

    print(f"{len(resolution.relevant)} answerable dev questions")
    print(f"hybrid's top 5 already the right drug: {right} of {top5} chunks ({right / top5:.1%})")
    print(f"questions the oracle cannot name (salt-only names): {unnamed}, left unfiltered\n")
    print(format_comparison(compare(hybrid, oracle, resolution.relevant, answers=answers),
                            "hybrid", "oracle-filter"))


if __name__ == "__main__":
    main()
