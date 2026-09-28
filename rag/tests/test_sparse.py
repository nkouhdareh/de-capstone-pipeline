"""Unit tests for the BM25 index and retriever.

A six-chunk corpus in a temporary folder stands in for the 360,916 real chunks.
The fast numpy index is checked against score_all(), the plain-Python formula in
bm25_text.py, so the two can only agree if both are right or both are wrong in
the same way, and the formula itself is checked by hand in test_bm25_text.py.
These need numpy, which CI does not install, so there they are skipped.
"""
import json

import pytest

np = pytest.importorskip("numpy")

from rag.index.bm25_text import TEXT_VERSION, bm25_text, score_all, tokenize
from rag.retrieve.sparse import SparseRetriever, TermIds, build_postings, save

ROWS = [
    ("c1", "Bruxism and nausea were reported.", "DULOXETINE", "CYMBALTA", "adverse_reactions"),
    ("c2", "Nausea, nausea and more nausea.", "DULOXETINE", None, "adverse_reactions"),
    ("c3", "Do not use with MAO inhibitors.", "DULOXETINE", None, "contraindications"),
    ("c4", "Hypomagnesemia has been reported with long use.", "PANTOPRAZOLE", "PROTONIX", "warnings_and_cautions"),
    ("c5", "Take one tablet daily.", "PANTOPRAZOLE", None, "dosage_and_administration"),
    ("c6", "Rash, fever and nausea.", "AMOXICILLIN", None, "adverse_reactions"),
]


def build(folder, rows=ROWS):
    index = build_postings(rows)
    save(index, folder, {"index": "test", "text": TEXT_VERSION, "stemmer": None,
                         "n_terms": len(index["terms"])})
    return SparseRetriever(folder)


def test_term_ids_give_the_same_terms_as_tokenize():
    """The build maps words through TermIds for speed, the query goes through
    tokenize(). If the two disagreed, a word could never be found."""
    stem = str.upper
    ids = TermIds(stem)
    words = "Is nausea listed on the label?".lower().split()
    words = [word.strip("?") for word in words]

    kept = [word for word in words if ids[word] >= 0]
    terms = list(ids.terms)

    assert [terms[ids[word]] for word in kept] == tokenize("Is nausea listed on the label?", stem)


def test_postings_hold_each_chunk_once_per_term_with_its_count():
    index = build_postings(ROWS)
    t = index["terms"].index("nausea")
    lo, hi = index["indptr"][t], index["indptr"][t + 1]

    chunks = [index["chunk_ids"][d] for d in index["postings_doc"][lo:hi]]
    counts = dict(zip(chunks, index["postings_tf"][lo:hi].tolist()))

    assert counts == {"c1": 1, "c2": 3, "c6": 1}


def test_the_index_scores_exactly_what_the_formula_says(tmp_path):
    retriever = build(tmp_path)
    docs = [tokenize(bm25_text(text, generic, brand, section)) for _, text, generic, brand, section in ROWS]

    for question in ["Is bruxism listed for duloxetine?", "nausea", "hypomagnesemia pantoprazole",
                     "What is PROTONIX?", "nausea nausea rash"]:
        expected = score_all(tokenize(question), docs)
        assert retriever.scores(question).tolist() == pytest.approx(expected, rel=1e-5)


def test_search_is_best_first_and_skips_chunks_with_no_matching_term(tmp_path):
    retriever = build(tmp_path)

    hits = retriever.search("hypomagnesemia", k=10)

    assert [chunk_id for chunk_id, _ in hits] == ["c4"]


def test_a_brand_name_finds_its_chunk_through_the_names_line(tmp_path):
    retriever = build(tmp_path)

    assert retriever.search("What is CYMBALTA?", k=1)[0][0] == "c1"


def test_a_question_with_no_known_word_returns_nothing(tmp_path):
    retriever = build(tmp_path)

    assert retriever.search("zzzz qqqq", k=5) == []
    assert retriever.search("", k=5) == []


def test_run_eval_interface_takes_a_gold_record_and_returns_ids(tmp_path):
    retriever = build(tmp_path)

    assert retriever({"qid": "d1", "question": "hypomagnesemia"}, 3) == ["c4"]


def test_k1_and_b_are_query_time_settings(tmp_path):
    """Raw counts are stored, so a different k1 needs no rebuild."""
    build(tmp_path)

    default = SparseRetriever(tmp_path).scores("nausea")
    flatter = SparseRetriever(tmp_path, k1=0.5).scores("nausea")

    assert not np.allclose(default, flatter)


def test_an_index_built_with_other_text_rules_is_refused(tmp_path):
    build(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["text"] = "bm25-v0"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="text rules"):
        SparseRetriever(tmp_path)
