"""Unit tests for the section-aware chunker.

Every test passes an explicit token counter and explicit window sizes, so the
suite needs no model download, no network and no corpus, and the arithmetic is
readable. `words` counts whitespace-separated tokens, which is close enough to
a real tokenizer for testing boundary logic and is exactly predictable.
"""
import pytest

from rag.corpus import chunker
from rag.corpus.chunker import (
    MAX_TOKENS,
    OTC_SAFETY_GROUP,
    atomize,
    chunk_section,
    context_header,
    merge_otc_safety,
    normalise_whitespace,
    pack,
    split_paragraphs,
    split_sentences,
    token_counter,
)


def words(text: str) -> int:
    return len(text.split())


def para(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def dense(text: str) -> int:
    """Adversarial counter: 3 tokens per word, which is what this corpus really
    costs once "hydrochlorothiazide" and "thrombocytopenia" are tokenized.

    `words` agrees with any word-ratio assumption in the code under test, so it
    cannot catch an estimation bug. This one can, and did: the first version of
    _hard_split assumed 1.4 tokens per word and produced 1,045-token chunks.
    """
    # Capped at len(text) to honour the precondition every real tokenizer
    # satisfies and the character fast paths rely on: a token is never fewer
    # than one character. Still ~3x adversarial for ordinary words.
    return min(len(text), len(text.split()) * 3) or 1


# --- whitespace -----------------------------------------------------------

def test_collapses_runs_of_spaces_but_keeps_paragraph_breaks():
    out = normalise_whitespace("a   b\t\tc\n\n\n\nd")
    assert out == "a b c\n\nd"


def test_empty_input_is_empty_not_none():
    assert normalise_whitespace("") == ""
    assert normalise_whitespace(None) == ""


# --- splitting ------------------------------------------------------------

def test_paragraph_split_drops_blank_fragments():
    assert split_paragraphs("one\n\n\n  \n\ntwo") == ["one", "two"]


def test_sentence_split_survives_clinical_abbreviations():
    """Unit abbreviations must not read as sentence ends. Unprotected this
    yields 'Give 5 mg.' / 'daily with food.', severing a dose from its
    frequency, which in a drug-safety corpus is the error that matters."""
    text = "Give 5 mg. daily with food. Do not exceed 10 mg. per day."
    assert len(split_sentences(text)) == 2


def test_sentence_split_handles_dosing_and_prose_abbreviations():
    text = "Take 250 mcg p.o. b.i.d. with water. Avoid alcohol, e.g. beer."
    assert len(split_sentences(text)) == 2


def test_masking_is_what_protects_unit_abbreviations():
    """Documents why _ABBREV_RE exists: the bare regex severs "5 mg." from its
    frequency, and the mask is the only thing preventing it."""
    unmasked = chunker._SENTENCE_SPLIT.split("Give 5 mg. Daily with food.")
    assert len(unmasked) == 2, "bare regex should split here"
    assert len(split_sentences("Give 5 mg. Daily with food.")) == 1


# --- the keep-whole path --------------------------------------------------

def test_section_under_the_cap_is_one_chunk_unchanged():
    text = "Do not use if you are allergic to aspirin."
    assert chunk_section(text, words, target=10, hard_max=15, min_tokens=3) == [text]


def test_section_below_the_floor_is_dropped():
    """`purpose` has a 26-character median. A 7-token vector is noise."""
    assert chunk_section("Questions?", words, min_tokens=3) == []


# --- the split path -------------------------------------------------------

def test_long_section_splits_into_several_chunks():
    text = "\n\n".join([para(12)] * 6)
    out = chunk_section(text, words, target=20, hard_max=30, min_tokens=3)
    assert len(out) > 1


def test_no_chunk_ever_exceeds_the_cap():
    """The invariant the whole design exists to protect."""
    text = "\n\n".join([para(37)] * 20)
    out = chunk_section(text, words, target=100, hard_max=120, min_tokens=5)
    assert out and all(words(c) <= 120 for c in out)


def test_splitting_loses_no_text():
    text = "\n\n".join([para(12, tag) for tag in "abcdef"])
    out = chunk_section(text, words, target=20, hard_max=30, min_tokens=3)
    assert " ".join(out).split() == text.split()


def test_a_stub_tail_is_folded_back_not_emitted():
    """A 2-token trailing chunk is worse than a slightly longer final one."""
    text = "\n\n".join([para(10)] * 3 + [para(1)])
    out = chunk_section(text, words, target=10, hard_max=12, min_tokens=5)
    assert all(words(c) >= 5 for c in out)


# --- atomize --------------------------------------------------------------

def test_cap_holds_when_text_is_token_dense():
    """The regression this file exists for. Real corpus, real tokenizer, 102
    chunks escaped the 480 cap and the largest was 1,045 tokens."""
    text = "\n\n".join([para(200)] * 4)
    out = chunk_section(text, dense, target=100, hard_max=120, min_tokens=5)
    assert out and all(dense(c) <= 120 for c in out)


def test_cap_holds_for_one_enormous_unbroken_sentence():
    """No paragraph or sentence boundary to fall back on."""
    out = chunk_section(para(500), dense, target=60, hard_max=90, min_tokens=5)
    assert out and all(dense(c) <= 90 for c in out)


def test_folding_a_stub_tail_does_not_breach_the_cap():
    text = "\n\n".join([para(9)] * 5 + [para(1)])
    out = chunk_section(text, dense, target=27, hard_max=30, min_tokens=6)
    assert all(dense(c) <= 30 for c in out)


def test_atomize_hard_splits_a_sentence_longer_than_the_window():
    """No sentence boundary to use, so it falls through to word groups."""
    units = atomize(para(100), dense, hard_max=20)
    assert units and all(dense(u) <= 20 for u in units)


def test_atomize_prefers_paragraph_boundaries():
    text = "\n\n".join([para(5), para(5)])
    assert atomize(text, words, hard_max=50) == [para(5), para(5)]


# --- pack -----------------------------------------------------------------

def test_pack_flushes_at_target_and_never_exceeds_max():
    units = [para(8)] * 5
    out = pack(units, words, target=16, hard_max=20)
    assert all(words(c) <= 20 for c in out)


# --- OTC merge ------------------------------------------------------------

def test_otc_fields_merge_in_drug_facts_panel_order():
    out = merge_otc_safety({"stop_use": "rash occurs", "do_not_use": "with an MAOI"})
    assert out.index("Do not use") < out.index("Stop use")


def test_otc_merge_keeps_field_provenance_readable():
    out = merge_otc_safety({"ask_doctor": "you have liver disease"})
    assert out == "Ask a doctor before use if: you have liver disease"


def test_otc_merge_skips_empty_and_missing_fields():
    assert merge_otc_safety({"stop_use": "", "do_not_use": "x", "ask_doctor": None}) \
        == "Do not use: x"


def test_otc_merge_of_nothing_is_empty():
    assert merge_otc_safety({}) == ""


def test_every_otc_field_has_a_human_label():
    assert set(OTC_SAFETY_GROUP) <= set(chunker.OTC_FIELD_LABELS)


# --- context header -------------------------------------------------------

def test_header_names_the_drug_and_the_part():
    h = context_header("CLOZAPINE", "CLOZARIL", "HLS Therapeutics",
                       "Adverse Reactions", 2, 5)
    assert "CLOZAPINE" in h and "CLOZARIL" in h
    assert "Part 2 of 5" in h and "Adverse Reactions" in h


def test_header_omits_part_when_the_section_was_not_split():
    assert "Part" not in context_header("ASPIRIN", "", "", "Warnings", 1, 1)


def test_header_does_not_repeat_the_name_when_brand_equals_generic():
    h = context_header("IBUPROFEN", "ibuprofen", "", "Warnings", 1, 1)
    assert h.count("IBUPROFEN") == 1 and "brand" not in h


def test_header_never_leaves_the_drug_blank():
    """An unnamed chunk is the orphan-chunk failure this header exists to fix."""
    assert "Unknown" in context_header("", "", "", "Warnings", 1, 1)


# --- tokenizer ------------------------------------------------------------

def test_counter_falls_back_to_characters_when_the_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(chunker, "_load_tokenizer", lambda _: None)
    count = token_counter()
    assert count("") >= 1
    assert count("a" * 40) == 10


@pytest.mark.parametrize("section", chunker.RX_SECTIONS + OTC_SAFETY_GROUP)
def test_allowlist_covers_every_declared_section(section):
    assert section in chunker.ALLOWLIST


def test_cap_leaves_headroom_under_the_model_limit():
    """480 not 512: embedding quality degrades approaching the limit, and the
    context header is prepended after chunking."""
    assert MAX_TOKENS < 512
