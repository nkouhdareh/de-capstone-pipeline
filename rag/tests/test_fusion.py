"""Unit tests for fusing the dense and BM25 rankings.

Pure Python, so these run in CI. Fake retrievers stand in for the real ones:
fusion only ever sees two ranked lists of (chunk_id, score).
"""
import pytest

from rag.retrieve.fusion import (
    HybridRetriever,
    collapse_near_copies,
    fuse,
    normalise,
    rrf,
    weighted_sum,
)


def test_rrf_by_hand():
    """k = 60. a is 1st in one list and 2nd in the other: 1/61 + 1/62.
    b is 2nd and 1st: the same. c is 3rd in one list only: 1/63."""
    fused = rrf([["a", "b", "c"], ["b", "a"]], k=60)

    assert fused == ["a", "b", "c"]            # a and b tie; a was seen first


def test_rrf_rewards_being_in_both_lists():
    """d is only 1st in one list: 1/61 = 0.0164. e is 3rd in both: 2/63 = 0.0317."""
    fused = rrf([["d", "x", "e"], ["y", "z", "e"]], k=60)

    assert fused[0] == "e"


def test_a_small_k_lets_one_top_rank_beat_two_middle_ranks():
    """k = 60: d, 1st once, is 1/61 = 0.016; e, 3rd twice, is 2/63 = 0.032.
    k = 0.5: d is 1/1.5 = 0.667 and e is 2/3.5 = 0.571, so d wins."""
    rankings = [["d", "x", "e"], ["y", "z", "e"]]

    assert rrf(rankings, k=60)[0] == "e"
    assert rrf(rankings, k=0.5)[0] == "d"


def test_minmax_puts_the_best_at_one_and_the_worst_at_zero():
    assert normalise([("a", 30.0), ("b", 20.0), ("c", 10.0)]) == {"a": 1.0, "b": 0.5, "c": 0.0}


def test_dbsf_maps_three_standard_deviations_to_the_ends_and_clips():
    """Scores 2, 4, 4, 4, 5, 5, 7, 9: mean 5, std 2, so -1 maps to 0 and 11 to 1.
    5 sits in the middle at 0.5."""
    scored = [(f"c{i}", s) for i, s in enumerate([9, 7, 5, 5, 4, 4, 4, 2])]

    normed = normalise(scored, "dbsf")

    assert normed["c2"] == pytest.approx(0.5)
    assert normed["c0"] == pytest.approx(10 / 12)
    assert all(0.0 <= value <= 1.0 for value in normed.values())


def test_normalise_handles_one_score_and_no_scores():
    assert normalise([("a", 3.0)]) == {"a": 1.0}
    assert normalise([]) == {}
    with pytest.raises(ValueError):
        normalise([("a", 1.0)], "zscore")


def test_weighted_sum_at_the_ends_is_one_retriever_alone():
    dense = [("a", 0.9), ("b", 0.8), ("c", 0.1)]
    sparse = [("c", 30.0), ("b", 10.0), ("a", 5.0)]

    assert weighted_sum(dense, sparse, dense_weight=1.0) == ["a", "b", "c"]
    assert weighted_sum(dense, sparse, dense_weight=0.0) == ["c", "b", "a"]


def test_weighted_sum_scores_a_chunk_missing_from_a_list_as_zero_there():
    """Weight 0.5, min-max. a: dense 1, missing from bm25 so 0, total 0.5.
    b: 0.5 and 0.5, total 0.5. c: dense 0, bm25 1, total 0.5. d: missing from
    dense, bm25's worst, total 0, so d comes last."""
    dense = [("a", 0.9), ("b", 0.6), ("c", 0.3)]
    sparse = [("c", 30.0), ("b", 20.0), ("d", 10.0)]

    fused = weighted_sum(dense, sparse, dense_weight=0.5)

    assert fused[-1] == "d"
    assert set(fused) == {"a", "b", "c", "d"}


def test_fuse_chooses_the_method():
    dense = [("a", 0.9), ("b", 0.8)]
    sparse = [("b", 12.0), ("c", 3.0)]

    assert fuse(dense, sparse, "rrf")[0] == "b"                     # in both lists
    assert fuse(dense, sparse, "minmax", dense_weight=1.0)[0] == "a"


class FakeRetriever:
    def __init__(self, scored):
        self.scored = scored
        self.asked = []

    def search(self, question, k):
        self.asked.append((question, k))
        return self.scored[:k]


def test_hybrid_asks_both_retrievers_for_depth_candidates_and_returns_k():
    dense = FakeRetriever([(f"d{i}", 1.0 - i / 100) for i in range(50)])
    sparse = FakeRetriever([(f"s{i}", 50.0 - i) for i in range(50)])
    hybrid = HybridRetriever(dense, sparse, depth=30)

    ids = hybrid({"qid": "q1", "question": "Is bruxism listed?"}, 5)

    assert len(ids) == 5
    assert dense.asked == sparse.asked == [("Is bruxism listed?", 30)]


def test_hybrid_puts_a_chunk_both_retrievers_found_first():
    dense = FakeRetriever([("x", 0.9), ("both", 0.8)])
    sparse = FakeRetriever([("y", 20.0), ("both", 15.0)])

    assert HybridRetriever(dense, sparse)({"question": "q"}, 3)[0] == "both"


# Near-copy collapse. A similarity table stands in for the dense vectors.

def similarity_from(pairs, default=0.5):
    table = {frozenset(pair): value for pair, value in pairs.items()}
    return lambda i, j: table.get(frozenset((i, j)), default)


def test_collapse_drops_a_near_copy_of_a_higher_chunk_and_keeps_order():
    """0 and 1 are copies; 3 copies 2. Kept: 0, 2, 4."""
    similar = similarity_from({(0, 1): 0.99, (2, 3): 0.97})

    assert collapse_near_copies(5, similar, threshold=0.95, k=10) == [0, 2, 4]


def test_collapse_stops_at_k_and_keeps_everything_below_the_threshold():
    assert collapse_near_copies(5, similarity_from({}), threshold=0.95, k=3) == [0, 1, 2]
    assert collapse_near_copies(3, similarity_from({(0, 1): 0.95}), threshold=0.95, k=3) == [0, 1, 2]


class FakeDense(FakeRetriever):
    """A dense retriever whose vectors are unit vectors given per chunk."""

    def __init__(self, scored, vectors):
        super().__init__(scored)
        self.vectors = vectors

    def vectors_of(self, chunk_ids):
        np = pytest.importorskip("numpy")
        return np.array([self.vectors[chunk_id] for chunk_id in chunk_ids], dtype=float)


def test_hybrid_with_collapse_returns_one_of_each_pair_of_copies():
    pytest.importorskip("numpy")
    dense = FakeDense([("a", 0.9), ("a-copy", 0.89), ("b", 0.5)],
                      {"a": [1, 0], "a-copy": [1, 0], "b": [0, 1], "c": [0.6, 0.8]})
    sparse = FakeRetriever([("a-copy", 9.0), ("c", 8.0)])

    ids = HybridRetriever(dense, sparse, collapse_above=0.95)({"question": "q"}, 3)

    assert ids == ["a-copy", "c", "b"]
