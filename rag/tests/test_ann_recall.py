"""Unit tests for the ANN measurement's two pure helpers. CI runs these; the
measurement itself needs faiss and the real index."""
from rag.eval.ann_recall import overlap, percentile


def test_overlap_is_the_share_of_the_exact_top_k_found():
    assert overlap([1, 2, 3, 4], [4, 3, 9, 8], k=4) == 0.5
    assert overlap([1, 2], [1, 2], k=2) == 1.0
    assert overlap([1, 2], [], k=2) == 0.0


def test_overlap_ignores_order():
    assert overlap([1, 2, 3], [3, 2, 1], k=3) == 1.0


def test_percentile_is_nearest_rank():
    values = [5.0, 1.0, 3.0, 2.0, 4.0]

    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == 5.0
    assert percentile(values, 0) == 1.0
