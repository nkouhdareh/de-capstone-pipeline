"""Unit tests for the refusal guardrail and its evaluation's pure rules.
Fakes stand in for the two retrievers, so CI runs these."""
import pytest

from rag.eval.guardrail_eval import auc, highest_cut
from rag.retrieve.guardrail import MIN_COSINE, Guardrail, decide, unknown_words


def test_unknown_words_keeps_order_and_drops_repeats():
    known = {"nausea", "listed"}.__contains__

    assert unknown_words(["gliclazide", "nausea", "gliclazide", "xyz"], known) == ("gliclazide", "xyz")


def test_an_unknown_word_refuses_whatever_the_cosine():
    verdict = decide(("domperidone",), 0.99)

    assert not verdict.answer and verdict.reason == "unknown words"


def test_a_low_cosine_refuses_and_a_high_one_answers():
    assert decide((), MIN_COSINE - 0.001).reason == "low similarity"
    assert decide((), MIN_COSINE).answer


class FakeDense:
    def __init__(self, cosine):
        self.cosine = cosine

    def search(self, question, k):
        return [("c1", self.cosine)]


class FakeSparse:
    def __init__(self):
        self.stem = None
        self.term_id = {"nausea": 0, "listed": 1, "metformin": 2}


def test_the_guardrail_names_the_word_no_chunk_contains():
    verdict = Guardrail(FakeDense(0.80), FakeSparse()).check("Is nausea listed for gliclazide?")

    assert verdict == (False, "unknown words", ("gliclazide",), 0.80)


def test_the_guardrail_answers_a_question_it_knows_every_word_of():
    assert Guardrail(FakeDense(0.80), FakeSparse()).check("Is nausea listed for metformin?").answer


def test_auc_by_hand():
    """Negatives 1 and 3, answerable 2 and 4: of four pairs, (1,2), (1,4) and
    (3,4) put the negative lower, so 3 of 4."""
    assert auc([2, 4], [1, 3]) == 0.75
    assert auc([5, 6], [1, 2]) == 1.0
    assert auc([1], [1]) == 0.5


def test_highest_cut_wrongly_refuses_at_most_two():
    scores = [0.70, 0.71, 0.72, 0.80]

    cut = highest_cut(scores, max_wrong=2)

    assert cut == pytest.approx(0.72)
    assert sum(s < cut for s in scores) == 2
