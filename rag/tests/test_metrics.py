"""Unit tests for the retrieval metrics.

The values are worked out by hand in the test names and comments, because a
metric that is only checked against its own implementation is not checked at
all. Everything is pure Python, so this runs in CI with only pytest installed.
"""
import pytest

from rag.eval.metrics import (
    bootstrap_ci,
    compare,
    evaluate,
    format_comparison,
    hit_at_k,
    ndcg,
    per_question,
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


# The paired comparison. B is always the candidate and A the one it is measured
# against, so a positive difference means B is better.

BETTER_RUN = {
    "q1": ["a", "x", "y"],                                  # rank 1, as before
    "q2": ["x", "b", "y"],                                  # rank 2, as before
    "q3": ["c", "x", "y"],                                  # rank 11 -> rank 1
    "q4": ["x", "y", "d"],                                  # nothing -> rank 3
}


def test_evaluate_reports_the_mean_of_the_per_question_scores():
    """evaluate() and compare() read the same per-question scores, so they
    cannot disagree about what a question scored."""
    scores = per_question(RUN, RELEVANT)

    assert list(scores) == list(evaluate(RUN, RELEVANT))
    assert scores["recall@5"] == {"q1": 1.0, "q2": 1.0, "q3": 0.0, "q4": 0.0}
    assert scores["mrr@10"] == {"q1": 1.0, "q2": 0.5, "q3": 0.0, "q4": 0.0}


def test_a_run_compared_with_itself_shows_no_difference():
    compared = compare(RUN, RUN, RELEVANT)

    for p in compared.values():
        assert (p.diff, p.low, p.high) == (0.0, 0.0, 0.0)
        assert (p.better, p.worse, p.same) == (0, 0, 4)
        assert p.verdict() == "no clear difference"


def test_compare_matches_hand_computed_differences():
    """recall@5: A finds q1, q2; B finds all four. 0.5 -> 1.0, B better on 2.
    MRR@10: A is (1 + 1/2 + 0 + 0) / 4 = 0.375, B is (1 + 1/2 + 1 + 1/3) / 4 = 0.7083."""
    compared = compare(RUN, BETTER_RUN, RELEVANT)

    recall = compared["recall@5"]
    assert (recall.a, recall.b, recall.diff) == (0.5, 1.0, 0.5)
    assert (recall.better, recall.worse, recall.same) == (2, 0, 2)
    assert compared["mrr@10"].a == pytest.approx(0.375)
    assert compared["mrr@10"].b == pytest.approx(0.70833, abs=1e-5)
    assert compared["mrr@10"].diff == pytest.approx(0.33333, abs=1e-5)
    assert compared["recall@20"].diff == pytest.approx(0.25)     # only q4 was missing at 20


def test_the_verdict_names_the_worse_run_as_worse():
    """A run that returns nothing, against a perfect one: B loses on every question."""
    compared = compare(perfect_run(RELEVANT), {}, RELEVANT)

    p = compared["recall@5"]
    assert (p.diff, p.low, p.high) == (-1.0, -1.0, -1.0)
    assert (p.better, p.worse, p.same) == (0, 4, 0)
    assert p.verdict("perfect", "empty") == "perfect better"


def test_pairing_separates_what_two_intervals_cannot():
    """The reason the comparison is paired. 40 questions: A finds 20, B finds the
    same 20 plus 4 more. Laid side by side, the two intervals overlap, so they
    cannot tell A from B. Paired, B is better on 4 questions and worse on none,
    and the interval of the difference sits clear of zero."""
    relevant = {f"q{i}": {f"a{i}"} for i in range(40)}
    run_a = {f"q{i}": [f"a{i}"] if i < 20 else ["x"] for i in range(40)}
    run_b = {f"q{i}": [f"a{i}"] if i < 24 else ["x"] for i in range(40)}

    alone_a = evaluate(run_a, relevant)["recall@5"]
    alone_b = evaluate(run_b, relevant)["recall@5"]
    paired = compare(run_a, run_b, relevant)["recall@5"]

    assert alone_b.low < alone_a.high, "side by side, the intervals overlap"
    assert paired.diff == pytest.approx(0.1)
    assert paired.low > 0
    assert paired.verdict("A", "B") == "B better"


def test_an_interval_that_touches_zero_names_no_winner():
    """3 wins of 40: some resamples hold none of the 3, so the interval's lower
    end is exactly 0. Not clear of zero, so no winner."""
    relevant = {f"q{i}": {f"a{i}"} for i in range(40)}
    run_a = {f"q{i}": [f"a{i}"] if i < 20 else ["x"] for i in range(40)}
    run_b = {f"q{i}": [f"a{i}"] if i < 23 else ["x"] for i in range(40)}

    paired = compare(run_a, run_b, relevant)["recall@5"]

    assert paired.diff > 0 and paired.low == 0.0
    assert paired.verdict() == "no clear difference"


def test_format_comparison_prints_one_row_per_metric_with_its_verdict():
    text = format_comparison(compare(RUN, BETTER_RUN, RELEVANT), "dense", "hybrid")

    assert "hybrid (B) against dense (A), the same 4 questions" in text
    assert "recall@5" in text and "ndcg@10" in text
    assert "+0.500" in text
