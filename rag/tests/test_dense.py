"""Unit tests for the dense retriever.

A tiny index in a temporary folder and a fake model stand in for the real 554 MB
index and the embedding model, so these run in milliseconds. They need numpy,
which CI does not install, so there they are skipped. The prefix string itself is
pinned by test_embedding_text.py, which does run in CI.
"""
import json

import pytest

np = pytest.importorskip("numpy")

from rag.index.embedding_text import MODEL_ID, QUERY_PREFIX
from rag.retrieve.dense import DenseRetriever, manifest_problems, top_k

GOOD_MANIFEST = {"model": MODEL_ID, "precision": "fp32",
                 "query_prefix": QUERY_PREFIX, "passage_prefix": ""}


class FakeModel:
    """Embeds any text as one fixed vector, and remembers what it was given."""

    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)
        self.seen = []

    def embed(self, texts):
        for text in texts:
            self.seen.append(text)
            yield self.vector


def write_index(folder, vectors, ids, **manifest):
    np.save(folder / "vectors.npy", np.asarray(vectors, dtype=np.float32))
    (folder / "chunk_ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({**GOOD_MANIFEST, **manifest}), encoding="utf-8")
    return folder


# Three chunks pointing along three different axes, so the closest one to any
# query is obvious by eye.
AXES = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def test_top_k_is_best_first_and_survives_a_k_larger_than_the_index():
    scores = np.array([0.1, 0.9, 0.5, 0.7])

    assert list(top_k(scores, 2)) == [1, 3]
    assert list(top_k(scores, 10)) == [1, 3, 2, 0]


def test_search_ranks_by_cosine_similarity(tmp_path):
    index = write_index(tmp_path, AXES, ["a", "b", "c"])
    retriever = DenseRetriever(index, model=FakeModel([0.1, 0.9, 0.3]))

    hits = retriever.search("any question", k=3)

    assert [chunk_id for chunk_id, _ in hits] == ["b", "c", "a"]
    assert hits[0][1] == pytest.approx(0.9)


def test_the_question_is_embedded_with_the_prefix(tmp_path):
    """The silent failure this whole file guards against."""
    model = FakeModel([1, 0, 0])
    DenseRetriever(write_index(tmp_path, AXES, ["a", "b", "c"]), model=model).search("Is it listed?")

    assert model.seen == [QUERY_PREFIX + "Is it listed?"]


def test_the_prefix_can_be_switched_off_to_measure_what_it_is_worth(tmp_path):
    model = FakeModel([1, 0, 0])
    index = write_index(tmp_path, AXES, ["a", "b", "c"])
    DenseRetriever(index, model=model, use_prefix=False).search("Is it listed?")

    assert model.seen == ["Is it listed?"]


def test_run_eval_interface_takes_a_gold_record_and_returns_ids(tmp_path):
    retriever = DenseRetriever(write_index(tmp_path, AXES, ["a", "b", "c"]),
                               model=FakeModel([0, 0, 1]))

    assert retriever({"qid": "d001", "question": "anything"}, 2) == ["c", "a"]


def test_a_matching_manifest_has_no_problems():
    assert manifest_problems(GOOD_MANIFEST) == []


@pytest.mark.parametrize("override, complaint", [
    ({"model": "some/other-model"}, "built with"),
    ({"query_prefix": "query: "}, "query prefix"),
    ({"passage_prefix": "passage: "}, "chunks embedded with prefix"),
])
def test_an_index_built_differently_is_refused(tmp_path, override, complaint):
    index = write_index(tmp_path, AXES, ["a", "b", "c"], **override)

    with pytest.raises(ValueError, match=complaint):
        DenseRetriever(index, model=FakeModel([1, 0, 0]))


def test_ids_and_vectors_out_of_step_are_refused(tmp_path):
    index = write_index(tmp_path, AXES, ["a", "b"])

    with pytest.raises(ValueError, match="chunk ids for"):
        DenseRetriever(index, model=FakeModel([1, 0, 0]))
