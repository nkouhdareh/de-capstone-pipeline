"""Unit tests for the prompt and the citation check. Pure Python: CI runs them."""
from rag.generate.prompt import (
    REFUSAL,
    Source,
    build_prompt,
    check_citations,
    cited_numbers,
    sentences,
)

SOURCES = [
    Source("c1", "PANTOPRAZOLE\nWarnings And Cautions\nHypomagnesemia has been reported with PPIs. "
                 "Monitor magnesium levels before treatment."),
    Source("c2", "PANTOPRAZOLE\nAdverse Reactions\nHeadache and diarrhea were the most common."),
]
QUESTION = "Does the pantoprazole label report low magnesium levels?"


def test_the_prompt_numbers_the_sources_and_repeats_the_question_after_them():
    system, user = build_prompt(QUESTION, SOURCES)

    assert REFUSAL in system
    assert user.index("[1] PANTOPRAZOLE") < user.index("[2] PANTOPRAZOLE") < user.index(QUESTION)


def test_cited_numbers_reads_every_citation_style():
    assert cited_numbers("A [1]. B [2][3] and [4, 5].") == [1, 2, 3, 4, 5]
    assert cited_numbers("No citation here.") == []


def test_sentences_split_after_the_citation():
    answer = "Hypomagnesemia was reported [1]. Monitor magnesium levels [1]."

    assert sentences(answer) == ["Hypomagnesemia was reported [1].", "Monitor magnesium levels [1]."]


def test_a_faithful_answer_passes():
    answer = "Yes, hypomagnesemia has been reported [1]. Monitor magnesium before treatment [1]."

    report = check_citations(answer, SOURCES, QUESTION)

    assert report.ok and not report.refused
    assert [check.support for check in report.checks] == [1.0, 1.0]


def test_a_claim_the_cited_source_never_makes_is_flagged():
    """Headache is in [2], not in [1]: citing [1] for it is the dangerous failure."""
    report = check_citations("Headache and diarrhea are common [1].", SOURCES, QUESTION)

    assert not report.ok and report.unsupported == 1


def test_an_uncited_sentence_and_a_citation_out_of_range_are_flagged():
    report = check_citations("Hypomagnesemia was reported. Monitor magnesium [7].", SOURCES, QUESTION)

    assert (report.uncited, report.invalid) == (1, 1)
    assert not report.ok


def test_the_exact_refusal_counts_as_a_refusal():
    report = check_citations(REFUSAL, SOURCES, QUESTION)

    assert report.refused and report.ok


def test_words_from_the_question_prove_nothing():
    """'magnesium' and 'pantoprazole' are in the question: only 'kidney failure'
    is new, and no source says it."""
    report = check_citations("Pantoprazole magnesium causes kidney failure [1].", SOURCES, QUESTION)

    assert report.unsupported == 1


def test_the_refusal_sentence_anywhere_in_the_answer_is_a_refusal():
    """A small model often adds a remark before the sentence it was told to use."""
    report = check_citations(f"Joint pain is not mentioned [1].\n\n{REFUSAL}", SOURCES, QUESTION)

    assert report.refused and report.ok


def test_a_rare_unsupported_word_outweighs_common_supported_ones():
    """'before', 'treatment' and 'PPIs' are in [1]; 'alopecia' and 'seen' are
    not. Counted equally, 3 of 5 words are found (0.6, a pass); weighted by
    rarity, the one that matters decides (2 of 10, flagged)."""
    answer = "Alopecia is seen before treatment with PPIs [1]."
    weights = {"alopecia": 8.0, "seen": 0.0, "before": 0.0, "treatment": 1.0, "ppis": 1.0}

    plain = check_citations(answer, SOURCES, QUESTION)
    weighted = check_citations(answer, SOURCES, QUESTION, weight=lambda word: weights.get(word, 1.0))

    assert plain.checks[0].support > 0.5
    assert weighted.checks[0].support == 0.2 and weighted.unsupported == 1


def test_a_models_own_citation_style_is_read_as_a_citation():
    """gpt-oss writes full-width brackets, sometimes with a dagger and a line
    range: U+3010 1 U+2020 L1-L4 U+3011. They mean [1]."""
    from rag.generate.prompt import normalise_citations

    answer = "Hypomagnesemia has been reported\u30101\u2020L1-L4\u3011\u30102\u3011. Monitor magnesium [1]."

    assert normalise_citations(answer) == "Hypomagnesemia has been reported[1][2]. Monitor magnesium [1]."
    report = check_citations(answer, SOURCES, QUESTION)
    assert report.uncited == 0 and report.checks[0].cited == (1, 2)


def test_a_sentence_with_nothing_to_back_needs_no_citation():
    """'Yes.' makes no claim a source could support, so it is not an uncited sentence."""
    report = check_citations("Yes. Hypomagnesemia has been reported [1].", SOURCES, QUESTION)

    assert report.ok and len(report.checks) == 1
