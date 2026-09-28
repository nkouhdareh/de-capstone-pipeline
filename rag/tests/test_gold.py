"""Unit tests for the gold set loader and the anchor resolver.

Each test builds a tiny corpus in memory, so the suite needs no parquet file, no
duckdb and no network, and runs in milliseconds. That is why the resolver's rule
is a pure function taking rows and a lookup, rather than a query.

The last test is different: it loads the real gold.jsonl, which is committed, so
CI checks the actual evaluation set on every pull request.
"""
import json

import pytest

from rag.eval.gold import (
    Anchor,
    anchors_of,
    drug_tokens,
    load_gold,
    match_anchors,
    match_equivalents,
)

WARNING_TEXT = "May cause drowsiness. Do not drive."


def test_span_resolves_to_the_chunk_containing_it():
    raw = [("set-1", "warnings", b"h1", "Do not use with alcohol."),
           ("set-1", "warnings", b"h2", WARNING_TEXT)]
    canonical = {("warnings", b"h1"): "chunk-a", ("warnings", b"h2"): "chunk-b"}

    relevant, unresolved = match_anchors(
        [Anchor("q1", "set-1", "warnings", "drowsiness")], raw, canonical)

    assert relevant == {"q1": frozenset({"chunk-b"})}
    assert unresolved == []


def test_duplicate_text_resolves_to_the_chunk_deduplication_kept():
    """The anchored label lost the (section, text_hash) tie-break, so its text
    lives on under another label's chunk id. This is the case that makes the
    resolver read chunks_raw: looking in chunks.parquet alone would find
    nothing for this label, and 57.6% of raw chunks are duplicates."""
    raw = [("set-9", "warnings", b"shared", WARNING_TEXT)]
    canonical = {("warnings", b"shared"): "chunk-kept-from-set-1"}

    relevant, unresolved = match_anchors(
        [Anchor("q1", "set-9", "warnings", "drowsiness")], raw, canonical)

    assert relevant == {"q1": frozenset({"chunk-kept-from-set-1"})}
    assert unresolved == []


def test_span_in_two_parts_resolves_to_both():
    """Both chunks answer the question, so recall may count either one."""
    raw = [("s", "adverse_reactions", b"h1", "Frequent: nausea, headache"),
           ("s", "adverse_reactions", b"h2", "Rare: nausea with vomiting")]
    canonical = {("adverse_reactions", b"h1"): "c1", ("adverse_reactions", b"h2"): "c2"}

    relevant, _ = match_anchors(
        [Anchor("q", "s", "adverse_reactions", "nausea")], raw, canonical)

    assert relevant["q"] == frozenset({"c1", "c2"})


def test_same_text_in_another_section_is_not_a_match():
    raw = [("s", "warnings", b"h1", WARNING_TEXT),
           ("s", "overdosage", b"h2", WARNING_TEXT)]
    canonical = {("warnings", b"h1"): "c1", ("overdosage", b"h2"): "c2"}

    relevant, _ = match_anchors([Anchor("q", "s", "warnings", "drowsiness")], raw, canonical)

    assert relevant["q"] == frozenset({"c1"})


def test_the_same_text_on_another_label_is_not_a_match():
    """fetch() returns the rows of every anchored label at once, so the rule has
    to key on set_id. A shared paragraph is not evidence about this label."""
    raw = [("another-label", "warnings", b"h1", WARNING_TEXT)]
    canonical = {("warnings", b"h1"): "c1"}

    relevant, unresolved = match_anchors(
        [Anchor("q", "my-label", "warnings", "drowsiness")], raw, canonical)

    assert relevant == {}
    assert unresolved == ["q"]


def test_a_span_that_is_gone_is_reported_not_raised():
    raw = [("s", "warnings", b"h1", "Nothing relevant here.")]
    canonical = {("warnings", b"h1"): "c1"}

    relevant, unresolved = match_anchors(
        [Anchor("q", "s", "warnings", "drowsiness")], raw, canonical)

    assert relevant == {}
    assert unresolved == ["q"]


def test_text_missing_from_the_current_index_is_unresolved_not_a_crash():
    """A raw chunk whose text is in no current chunk. A rebuilt index is exactly
    when this happens, and it must produce a report rather than a KeyError."""
    raw = [("s", "warnings", b"gone", WARNING_TEXT)]

    relevant, unresolved = match_anchors(
        [Anchor("q", "s", "warnings", "drowsiness")], raw, {})

    assert relevant == {}
    assert unresolved == ["q"]


def test_matching_is_exact_not_case_insensitive():
    """finalize_gold only accepts a span that appears word for word, so exact is
    the contract. A near miss must show up as unresolved, not as a silent pass."""
    raw = [("s", "warnings", b"h", "May cause Drowsiness.")]
    canonical = {("warnings", b"h"): "c"}

    relevant, unresolved = match_anchors(
        [Anchor("q", "s", "warnings", "drowsiness")], raw, canonical)

    assert relevant == {}
    assert unresolved == ["q"]


def question(qid="q1", qtype="lookup", split="dev", anchor=True):
    return {"qid": qid, "split": split, "qtype": qtype, "question": "does it?",
            "anchor": {"set_id": "s", "section": "warnings", "answer_span": "x"}
            if anchor else None}


def write_gold(tmp_path, records):
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_load_gold_filters_by_split(tmp_path):
    path = write_gold(tmp_path, [question("q1", split="dev"), question("q2", split="test")])

    assert [q["qid"] for q in load_gold(path, split="dev")] == ["q1"]
    assert [q["qid"] for q in load_gold(path, split="test")] == ["q2"]
    assert len(load_gold(path)) == 2


def test_load_gold_rejects_a_negative_carrying_an_anchor(tmp_path):
    path = write_gold(tmp_path, [question("q1", qtype="negative", anchor=True)])

    with pytest.raises(ValueError, match="negatives"):
        load_gold(path)


def test_load_gold_rejects_an_answerable_question_without_an_anchor(tmp_path):
    path = write_gold(tmp_path, [question("q1", qtype="lookup", anchor=False)])

    with pytest.raises(ValueError, match="negatives"):
        load_gold(path)


def test_load_gold_rejects_a_repeated_qid(tmp_path):
    path = write_gold(tmp_path, [question("q1"), question("q1")])

    with pytest.raises(ValueError, match="repeated"):
        load_gold(path)


def test_load_gold_rejects_an_unknown_split(tmp_path):
    path = write_gold(tmp_path, [question("q1", split="train")])

    with pytest.raises(ValueError, match="dev or test"):
        load_gold(path)


def test_anchors_of_skips_negatives():
    questions = [question("q1"), question("q2", qtype="negative", anchor=False)]

    assert [a.qid for a in anchors_of(questions)] == ["q1"]


def test_the_committed_gold_set_is_valid_and_balanced():
    """Runs against the real rag/eval/gold/gold.jsonl. It is the one file in
    Phase 2 that is committed, so this check runs in CI too."""
    questions = load_gold()
    negatives = [q for q in questions if q["qtype"] == "negative"]
    dev = [q for q in questions if q["split"] == "dev"]

    assert len(questions) >= 100, "too small to separate a 0.70 system from a 0.80 one"
    assert 0.15 <= len(negatives) / len(questions) <= 0.25
    assert 0.55 <= len(dev) / len(questions) <= 0.65
    assert all(q["anchor"]["answer_span"] for q in questions if q["qtype"] != "negative")


def asked(qid="q1", qtype="lookup", drug="DULOXETINE", brand=None):
    return {"qid": qid, "qtype": qtype, "drug": drug, "brand": brand,
            "anchor": {"set_id": "s", "section": "adverse_reactions", "answer_span": "bruxism"}}


def test_drug_tokens_ignore_salts_and_forms_but_not_a_second_drug():
    assert drug_tokens("DULOXETINE HYDROCHLORIDE") == drug_tokens("Duloxetine") == {"DULOXETINE"}
    assert drug_tokens("AMLODIPINE BESYLATE TABLETS") == {"AMLODIPINE"}
    assert drug_tokens("AMLODIPINE BESYLATE AND BENAZEPRIL") == {"AMLODIPINE", "BENAZEPRIL"}
    assert drug_tokens(None) == frozenset()


def test_the_same_answer_on_another_label_of_the_same_drug_counts():
    """The case the first dense run exposed: 16 of its 48 misses were this."""
    rows = [("q1", "other-label", "DULOXETINE HCL", "Cymbalta")]

    assert match_equivalents([asked()], rows) == {"q1": frozenset({"other-label"})}


def test_the_same_sentence_for_a_different_drug_does_not_count():
    rows = [("q1", "c1", "VENLAFAXINE", None)]

    assert match_equivalents([asked()], rows) == {}


def test_a_combination_product_is_a_different_drug():
    rows = [("q1", "c1", "AMLODIPINE BESYLATE AND BENAZEPRIL", None)]

    assert match_equivalents([asked(drug="AMLODIPINE")], rows) == {}


def test_identifier_questions_match_on_the_brand():
    """A brand question names one product. Another brand of the same generic is
    not the label it asked about."""
    rows = [("q1", "same-brand", "OXYCODONE AND ACETAMINOPHEN", "Percocet"),
            ("q1", "other-brand", "OXYCODONE AND ACETAMINOPHEN", "Endocet")]
    question = asked(qtype="identifier", drug="OXYCODONE AND ACETAMINOPHEN", brand="PERCOCET")

    assert match_equivalents([question], rows) == {"q1": frozenset({"same-brand"})}


def test_a_name_with_no_significant_words_never_matches():
    """SODIUM CHLORIDE is all salt words. Rather than match everything, the
    question stays strict."""
    rows = [("q1", "c1", "SODIUM CHLORIDE", None)]

    assert match_equivalents([asked(drug="SODIUM CHLORIDE")], rows) == {}


def test_rows_for_questions_without_an_anchor_are_ignored():
    negative = {"qid": "n1", "qtype": "negative", "drug": "DULOXETINE", "anchor": None}

    assert match_equivalents([negative], [("n1", "c1", "DULOXETINE", None)]) == {}
