"""Unit tests for the reranker wrapper. A fake model stands in for the
cross-encoder, so these need no model, no numpy and no duckdb: CI runs them."""
from rag.retrieve.rerank import Reranker, by_score


class FakeCrossEncoder:
    """Scores a document by how many of the question's words it contains."""

    def __init__(self):
        self.seen = []

    def rerank(self, query, documents, batch_size):
        self.seen.append(list(documents))
        words = set(query.lower().split())
        for document in documents:
            yield float(len(words & set(document.lower().split())))


TEXTS = {"a": "take one tablet daily", "b": "bruxism was reported", "c": "bruxism and nausea reported"}


def test_by_score_is_best_first_and_keeps_input_order_on_ties():
    assert by_score(["a", "b", "c"], [1.0, 3.0, 1.0]) == [("b", 3.0), ("a", 1.0), ("c", 1.0)]


def test_rerank_reads_each_chunks_text_and_reorders():
    model = FakeCrossEncoder()
    reranker = Reranker(texts=TEXTS, model=model)

    ranked = reranker.rerank("was bruxism reported", ["a", "b", "c"])

    assert [chunk_id for chunk_id, _ in ranked] == ["b", "c", "a"]
    assert model.seen == [[TEXTS["a"], TEXTS["b"], TEXTS["c"]]]


def test_no_candidates_means_no_model_call():
    model = FakeCrossEncoder()

    assert Reranker(texts=TEXTS, model=model).rerank("anything", []) == []
    assert model.seen == []
