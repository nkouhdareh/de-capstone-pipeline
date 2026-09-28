"""Phase 4: hybrid retrieval, dense and BM25 fused into one ranking.

Both retrievers return their top `depth` chunks, and the two lists become one.
Two ways of doing that, both measured on dev:

Reciprocal Rank Fusion (RRF) uses only positions:

    score(chunk) = sum over the lists it is in of  1 / (k + rank)

Rank 1 in one list is worth 1/(k+1). A small k rewards the top of each list
heavily; a large k flattens the curve, so being in both lists matters more than
where. Scores never enter, so it does not matter that cosine similarity runs
from 0 to 1 and BM25 from 0 to about 40. k = 60 is the value from the original
paper (Cormack, Clarke and Buettcher, 2009).

A weighted sum uses the scores, so it has to put them on one scale first:

    score(chunk) = w * dense_norm + (1 - w) * bm25_norm

Each list is normalised on its own, and a chunk missing from a list gets 0 from
it, as if it scored as low as that list's worst. Two normalisations:

    minmax   (s - min) / (max - min): the best in the list is 1, the worst 0
    dbsf     Qdrant's distribution-based score fusion: mean - 3 std maps to 0
             and mean + 3 std to 1, clipped, so one outlier cannot squash the rest

Pure Python, no numpy: a fused list is at most 200 chunks, and keeping it pure
lets the tests run in CI.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean, pstdev

RRF_K = 60
DEPTH = 100          # candidates taken from each retriever before fusing
DENSE_WEIGHT = 0.5

Scored = Sequence[tuple[str, float]]    # (chunk_id, score), best first


def rrf(rankings: Sequence[Sequence[str]], k: float = RRF_K) -> list[str]:
    """Chunk ids fused by reciprocal rank, best first. Ties keep the order in
    which the chunks were first seen, so the result never depends on hashing."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda chunk_id: -scores[chunk_id])


def normalise(scored: Scored, method: str = "minmax") -> dict[str, float]:
    """One retriever's scores on a 0 to 1 scale, by chunk id."""
    if not scored:
        return {}
    values = [score for _, score in scored]
    if method == "minmax":
        low, high = min(values), max(values)
    elif method == "dbsf":
        centre, spread = fmean(values), pstdev(values)
        low, high = centre - 3 * spread, centre + 3 * spread
    else:
        raise ValueError(f"unknown normalisation {method!r}")
    if high <= low:
        return {chunk_id: 1.0 for chunk_id, _ in scored}
    return {chunk_id: min(1.0, max(0.0, (score - low) / (high - low))) for chunk_id, score in scored}


def weighted_sum(dense: Scored, sparse: Scored, dense_weight: float = DENSE_WEIGHT,
                 method: str = "minmax") -> list[str]:
    """Chunk ids fused by a weighted sum of normalised scores, best first."""
    d, s = normalise(dense, method), normalise(sparse, method)
    order = list(dict.fromkeys([chunk_id for chunk_id, _ in dense] + [chunk_id for chunk_id, _ in sparse]))
    fused = {chunk_id: dense_weight * d.get(chunk_id, 0.0) + (1 - dense_weight) * s.get(chunk_id, 0.0)
             for chunk_id in order}
    return sorted(order, key=lambda chunk_id: -fused[chunk_id])


def fuse(dense: Scored, sparse: Scored, method: str = "rrf", rrf_k: float = RRF_K,
         dense_weight: float = DENSE_WEIGHT) -> list[str]:
    if method == "rrf":
        return rrf([[chunk_id for chunk_id, _ in dense], [chunk_id for chunk_id, _ in sparse]], rrf_k)
    return weighted_sum(dense, sparse, dense_weight, method)


class HybridRetriever:
    """Any two retrievers with search(question, k) -> [(chunk_id, score)], fused.
    method is "rrf", "minmax" or "dbsf"."""

    def __init__(self, dense, sparse, method: str = "rrf", rrf_k: float = RRF_K,
                 dense_weight: float = DENSE_WEIGHT, depth: int = DEPTH):
        self.dense, self.sparse = dense, sparse
        self.method, self.rrf_k, self.dense_weight, self.depth = method, rrf_k, dense_weight, depth

    def search(self, question: str, k: int = 20) -> list[str]:
        depth = max(k, self.depth)
        fused = fuse(self.dense.search(question, depth), self.sparse.search(question, depth),
                     self.method, self.rrf_k, self.dense_weight)
        return fused[:k]

    def __call__(self, question: Mapping, k: int) -> list[str]:
        """The retriever interface run_eval expects: a gold record in, chunk ids out."""
        return self.search(question["question"], k)
