"""Unit tests for what BM25 reads and for the BM25 formula.

Pure Python, so these run in CI with only pytest installed. The stemmer is a
compiled library CI does not have, so its one test is skipped there.
"""
from math import log

import pytest

from rag.index.bm25_text import (
    K1,
    STOPWORDS,
    B,
    bm25_text,
    distinct,
    idf,
    score_all,
    term_weight,
    tokenize,
)


def test_tokenize_lowercases_and_splits_on_anything_not_a_letter_or_digit():
    assert tokenize("QT-prolongation (Torsade)") == ["qt", "prolongation", "torsade"]


def test_an_ndc_code_becomes_its_digit_groups():
    assert tokenize("NDC 0078-0357-05") == ["ndc", "0078", "0357", "05"]


def test_tokenize_drops_lucenes_33_stopwords():
    assert len(STOPWORDS) == 33
    assert tokenize("Is it listed on the label of this drug?") == ["listed", "label", "drug"]


def test_tokenize_applies_the_stemmer_it_is_given():
    assert tokenize("Headaches, rashes", stem=lambda word: word.rstrip("s")) == ["headache", "rashe"]


def test_bm25_text_keeps_every_name_and_the_section_title():
    text = bm25_text("Nausea was common.", "OLANZAPINE", "ZYPREXA", "adverse_reactions")

    assert text == "OLANZAPINE (brand ZYPREXA)\nAdverse Reactions\nNausea was common."


def test_bm25_text_never_trims_long_names():
    """The embedding model has a 512-token window, BM25 has none."""
    names = " AND ".join(f"INGREDIENT{i}" for i in range(200))

    assert names in bm25_text("text", names, None, "warnings")


def test_distinct_keeps_first_seen_order():
    assert distinct(["rash", "fever", "rash"]) == ["rash", "fever"]


def test_idf_is_lucenes_and_never_negative():
    """ln(1 + (10 - 1 + 0.5) / (1 + 0.5)) = ln(7.333) = 1.9924.
    A term in every document still scores above zero."""
    assert idf(1, 10) == pytest.approx(log(1 + 9.5 / 1.5))
    assert idf(1, 10) == pytest.approx(1.99243, abs=1e-5)
    assert 0 < idf(10, 10) < idf(5, 10) < idf(1, 10)


def test_term_weight_by_hand():
    """tf 2, a chunk of average length, idf 1: 2 * 2.2 / (2 + 1.2) = 1.375."""
    assert term_weight(2, 100, 100, 1.0) == pytest.approx(1.375)
    assert (K1, B) == (1.2, 0.75)


def test_repeats_count_less_and_less():
    """k1 caps what repeats are worth: ten mentions are worth far less than ten
    times one mention, and never more than idf * (k1 + 1)."""
    once = term_weight(1, 100, 100, 1.0)
    ten = term_weight(10, 100, 100, 1.0)

    assert once < ten < 10 * once
    assert term_weight(10_000, 100, 100, 1.0) < 1.0 * (K1 + 1)


def test_a_long_chunk_is_marked_down_unless_b_is_zero():
    assert term_weight(1, 400, 100, 1.0) < term_weight(1, 100, 100, 1.0)
    assert term_weight(1, 400, 100, 1.0, b=0.0) == term_weight(1, 100, 100, 1.0, b=0.0)


def test_a_rare_term_outscores_a_common_one():
    """Why BM25 finds identifiers: a word on few chunks carries a high idf."""
    docs = [["tablet", "bruxism"], ["tablet", "nausea"], ["tablet", "nausea"], ["tablet", "rash"]]

    scores = score_all(["bruxism"], docs)
    common = score_all(["tablet"], docs)

    assert scores.index(max(scores)) == 0
    assert max(scores) > max(common)


def test_score_all_scores_zero_where_no_term_matches_and_ignores_repeats_in_the_query():
    docs = [["rash"], ["fever"]]

    assert score_all(["rash"], docs)[1] == 0.0
    assert score_all(["rash", "rash"], docs) == score_all(["rash"], docs)
    assert score_all(["rash"], []) == []


def test_the_english_stemmer_joins_plural_and_singular():
    pytest.importorskip("py_rust_stemmers")
    from rag.index.bm25_text import english_stemmer

    stem = english_stemmer()

    assert tokenize("headaches", stem) == tokenize("headache", stem) == ["headach"]
