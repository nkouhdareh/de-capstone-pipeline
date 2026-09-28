"""Unit tests for what the embedding model reads.

A fake counter (whitespace words) keeps the arithmetic readable and the suite
free of models, numpy and network, so it runs in CI with only pytest.
"""
import pytest

from rag.index.embedding_text import (
    QUERY_PREFIX,
    TRIMMED,
    passage_text,
    query_text,
)

BODY = "May cause drowsiness. Do not drive."


def words(text: str) -> int:
    return len(text.split())


def test_query_prefix_is_exactly_the_model_card_string():
    """Copied from the Snowflake model card. A near miss fails silently at
    search time, so the exact string is pinned here, trailing space included."""
    assert QUERY_PREFIX == "Represent this sentence for searching relevant passages: "


def test_questions_get_the_prefix_and_chunks_do_not():
    assert query_text("Is nausea listed?") == QUERY_PREFIX + "Is nausea listed?"
    passage = passage_text(BODY, "CLOZAPINE", "CLOZARIL", "warnings", words)
    assert not passage.startswith(QUERY_PREFIX)


def test_compact_header_names_drug_brand_and_section_only():
    passage = passage_text(BODY, "CLOZAPINE", "CLOZARIL", "adverse_reactions", words)

    assert passage == ("Drug: CLOZAPINE (brand CLOZARIL)\n"
                       "Section: Adverse Reactions\n\n" + BODY)
    assert "Manufacturer" not in passage and "Part" not in passage


def test_brand_is_dropped_when_it_only_repeats_the_generic():
    passage = passage_text(BODY, "Duloxetine", "DULOXETINE", "warnings", words)

    assert passage.startswith("Drug: Duloxetine\n")


def test_missing_names_fall_back_to_brand_then_unknown():
    assert passage_text(BODY, None, "TYLENOL", "warnings", words).startswith("Drug: TYLENOL\n")
    assert passage_text(BODY, None, None, "warnings", words).startswith("Drug: Unknown\n")


def test_long_drug_names_are_trimmed_until_the_whole_text_fits():
    """The homeopathic-remedy case: a drug 'name' that is 20 ingredients long."""
    names = " ".join(f"INGREDIENT{i}" for i in range(20))
    passage = passage_text(BODY, names, None, "warnings", words, limit=15)

    assert words(passage) <= 15
    assert passage.startswith("Drug: INGREDIENT0")
    assert TRIMMED in passage


def test_the_chunk_text_itself_is_never_cut():
    names = " ".join(f"INGREDIENT{i}" for i in range(20))
    passage = passage_text(BODY, names, None, "warnings", words, limit=15)

    assert passage.endswith("\n\n" + BODY)


def test_a_text_that_fits_exactly_is_left_whole():
    passage = passage_text(BODY, "CLOZAPINE", None, "warnings", words)
    limit = words(passage)

    assert passage_text(BODY, "CLOZAPINE", None, "warnings", words, limit=limit) == passage


def test_a_chunk_over_the_limit_on_its_own_is_refused():
    """That can only happen if the chunker's 480-token cap was broken upstream,
    and embedding it would silently lose its end."""
    with pytest.raises(ValueError, match="cap was broken"):
        passage_text(BODY, "X", None, "warnings", words, limit=3)
