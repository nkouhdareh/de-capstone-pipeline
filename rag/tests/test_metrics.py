"""Unit tests for the retrieval metrics.

The values are worked out by hand in the test names and comments, because a
metric that is only checked against its own implementation is not checked at
all. Everything is pure Python, so this runs in CI with only pytest installed.
"""
import pytest

from rag.eval.metrics import (
    bootstrap_ci,
    evaluate,
    hit_at_k,
    ndcg,
    reciprocal_rank,
)


def test_hit_counts_only_inside_the_cut_off():
    ranked = ["a", "b", "c", "d", "e", "target"]

    assert hit_at_k(ranked, {"target"}, 5) == 0.0
    assert hit_at_k(ranked, {"target"}, 6) == 1.0


def test_hit_needs_only_one_of_several_answers():
    """10 gold questions have their answer in two chunks. Either one is a hit."""
    ranked = ["x", "second-copy", "y"]

    assert hit_at_k(ranked, {"first-copy", "second-copy"}, 5) == 1.0


def test_hit_is_zero_when_nothing_was_returned():
    assert hit_at_k([], {"target"}, 10) == 0.0


def test_reciprocal_rank_is_one_over_the_first_hit():
    assert reciprocal_rank(["target", "b", "c"], {"target"}) == 1.0
    assert reciprocal_rank(["a", "b", "c", "target"], {"target"}) == 0.25


def test_reciprocal_rank_ignores_hits_past_the_cut_off():
    ranked = [f"miss{i}" for i in range(10)] + ["target"]

    assert reciprocal_rank(ranked, {"target"}, k=10) == 0.0


def test_ndcg_is_one_when_the_answer_is_first():
    assert ndcg(["target", "b"], {"target"}) == 1.0


def test_ndcg_discounts_by_position():
    """One answer at rank 2: 1/log2(3) = 0.6309."""
    assert ndcg(["b", "target"], {"target"}) == pytest.approx(0.63093, abs=1e-5)


def test_ndcg_with_two_answers_wants_both_at_the_top():
    """Ideal is 1/log2(2) + 1/log2(3) = 1.6309.
    Ranks 1 and 3 give 1/log2(2) + 1/log2(4) = 1.5, so 1.5/1.6309 = 0.9197."""
    assert ndcg(["a1", "x", "a2"], {"a1", "a2"}) == pytest.approx(0.91972, abs=1e-5)
    assert ndcg(["a1", "a2", "x"], {"a1", "a2"}) == 1.0


def test_ndcg_is_zero_with_no_answers_or_no_results():
    assert ndcg(["a", "b"], set()) == 0.0
    assert ndcg([], {"target"}) == 0.0


def test_bootstrap_interval_is_flat_when_every_question_scores_the_same():
    low, high = bootstrap_ci([1.0] * 20)

    assert low == 1.0 and high == 1.0


def test_bootstrap_is_reproducible_and_brackets_the_mean():
    scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]   # mean 0.6

    interval = bootstrap_ci(scores)

    assert interval == bootstrap_ci(scores), "same seed must give the same interval"
    assert interval[0] <= 0.6 <= interval[1]
    # 2,000 rounds is enough that the seed barely moves the answer. That is the
    # property worth having: a published interval should not depend on a seed.
    other = bootstrap_ci(scores, seed=7)
    assert abs(other[0] - interval[0]) <= 0.1
    assert abs(other[1] - interval[1]) <= 0.1


def test_more_questions_give_a_narrower_interval():
    """The reason the gold set has 139 questions and not 30."""
    small = bootstrap_ci([1.0, 0.0] * 15)
    large = bootstrap_ci([1.0, 0.0] * 150)

    assert (large[1] - large[0]) < (small[1] - small[0])


def perfect_run(relevant):
    return {qid: list(answers) for qid, answers in relevant.items()}


RELEVANT = {"q1": {"a"}, "q2": {"b"}, "q3": {"c"}, "q4": {"d"}}
RUN = {
    "q1": ["a", "x", "y"],                                  # hit at rank 1
    "q2": ["x", "b", "y"],                                  # hit at rank 2
    "q3": [f"miss{i}" for i in range(10)] + ["c"],          # hit at rank 11
    "q4": [],                                               # nothing returned
}


def test_evaluate_matches_hand_computed_values():
    scored = evaluate(RUN, RELEVANT)

    assert scored["recall@1"].value == pytest.approx(0.25)    # only q1
    assert scored["recall@5"].value == pytest.approx(0.50)    # q1, q2
    assert scored["recall@10"].value == pytest.approx(0.50)   # q3 is at rank 11
    assert scored["recall@20"].value == pytest.approx(0.75)   # q1, q2, q3
    assert scored["mrr@10"].value == pytest.approx((1 + 0.5) / 4)
    assert scored["ndcg@10"].value == pytest.approx((1 + 0.63093) / 4, abs=1e-5)
    assert scored["recall@5"].n == 4


def test_a_perfect_retriever_scores_one_everywhere():
    """The gate for run_eval: if this is not 1.0, the harness is wrong, not the
    retriever."""
    scored = evaluate(perfect_run(RELEVANT), RELEVANT)

    assert all(metric.value == 1.0 for metric in scored.values())
    assert all(metric.low == 1.0 and metric.high == 1.0 for metric in scored.values())


def test_a_retriever_that_returns_nothing_scores_zero_everywhere():
    scored = evaluate({}, RELEVANT)

    assert all(metric.value == 0.0 for metric in scored.values())
    assert scored["recall@5"].n == 4, "missing answers are misses, not skips"


def test_negatives_are_not_scored():
    """Negatives have no relevant chunks, so they never enter these numbers."""
    scored = evaluate({"neg1": ["anything"]}, RELEVANT)

    assert scored["recall@5"].n == 4


def test_ndcg_counts_copies_of_one_answer_once():
    """Three labels printing the same sentence are one answer, not three, so
    stacking the copies at the top earns nothing extra."""
    copies = {"copy1", "copy2", "copy3"}

    assert ndcg(["copy1", "copy2", "copy3"], copies, answers=1) == 1.0
    assert ndcg(["other", "copy2", "copy3"], copies, answers=1) == pytest.approx(0.63093, abs=1e-5)


def test_evaluate_hands_the_number_of_answers_to_ndcg():
    """Counted as two answers, the second copy at rank 3 adds gain: 0.6934.
    Counted as one answer in two copies, only the first hit at rank 2 does: 0.6309."""
    run, relevant = {"q1": ["x", "a", "a-copy"]}, {"q1": {"a", "a-copy"}}

    assert evaluate(run, relevant)["ndcg@10"].value == pytest.approx(0.69343, abs=1e-5)
    assert evaluate(run, relevant, answers={"q1": 1})["ndcg@10"].value == pytest.approx(0.63093, abs=1e-5)
