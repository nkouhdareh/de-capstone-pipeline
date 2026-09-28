"""Unit tests for the drug-filter ceiling's pure rules. CI runs these."""
from rag.eval.filter_ceiling import index_names, oracle_allowed, top_up

NAMES = index_names([
    ("c1", "DULOXETINE HYDROCHLORIDE", "Cymbalta"),
    ("c2", "Duloxetine", "Drizalma Sprinkle"),
    ("c3", "DULOXETINE AND SOMETHING", None),
    ("c4", "ZINC SULFATE", None),
])
LOOKUP = {"qtype": "lookup", "drug": "DULOXETINE", "brand": "CYMBALTA"}
IDENTIFIER = {"qtype": "identifier", "drug": "DULOXETINE", "brand": "CYMBALTA"}


def test_the_oracle_matches_the_generic_whatever_the_salt():
    assert oracle_allowed(LOOKUP, *NAMES) == ["c1", "c2"]


def test_identifier_questions_match_the_brand_not_the_generic():
    assert oracle_allowed(IDENTIFIER, *NAMES) == ["c1"]


def test_a_salt_only_name_is_never_matched():
    """ZINC SULFATE has no significant words once salts are ignored: the ADR-005
    problem, so the oracle leaves such a question unfiltered."""
    question = {"qtype": "paraphrase", "drug": "ZINC SULFATE", "brand": None}

    assert oracle_allowed(question, *NAMES) == []


def test_top_up_keeps_the_filtered_order_and_fills_without_repeats():
    assert top_up(["a", "b"], ["b", "x", "a", "y", "z"], 4) == ["a", "b", "x", "y"]
    assert top_up(["a", "b", "c"], ["x"], 2) == ["a", "b"]
    assert top_up([], ["x", "y"], 5) == ["x", "y"]
