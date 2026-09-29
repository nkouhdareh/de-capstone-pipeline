"""Unit tests for the miss diagnosis's pure rules. CI runs these."""
from rag.eval.diagnose_misses import first_hit, miss_class, near_copies


def test_first_hit_is_the_rank_of_the_first_answer():
    assert first_hit(["x", "a", "y", "b"], {"a", "b"}) == 2
    assert first_hit(["x", "y"], {"a"}) is None


def test_miss_class_boundaries():
    assert [miss_class(r) for r in (1, 5, 6, 20, 21, 100, None)] == [
        "top 5", "top 5", "rank 6-20", "rank 6-20", "rank 21-100", "rank 21-100", "not in top 100"]


def test_near_copies_counts_places_that_copy_one_above():
    """Positions 0 and 2 are the same paragraph, 1 and 3 are different."""
    same = {(2, 0)}

    assert near_copies(4, lambda i, j: 0.99 if (i, j) in same else 0.5, threshold=0.95) == 1
    assert near_copies(1, lambda i, j: 1.0) == 0
