"""Retrieval metrics, in pure Python.

No numpy on purpose. rag/tests runs in CI with nothing installed but pytest, and
this arithmetic is short enough to read, which matters more here than speed: the
whole point of the harness is that every number in the write-up can be traced to
a formula someone can check.

"recall@k" means two different things in the literature, so this one is stated:

    recall@k here is hit rate. A question counts as found if ANY chunk that
    answers it is in the top k. 10 of the 114 answerable questions have their
    answer in two chunks, and either one answers the question, so the other
    definition (the share of relevant chunks retrieved) would punish a retriever
    for not also returning the redundant copy.

    MRR@10 rewards putting the answer first: 1 over the rank of the first chunk
    that answers, and 0 when none of the top 10 does.

    nDCG@10 is the standard one: binary relevance, log2 discount, ideal ranking
    capped at k. Unlike recall it does want both chunks when a question has two,
    which makes it the stricter companion to recall rather than a duplicate of it.

Every metric is a mean over questions, reported with a 95% bootstrap interval.
At n=56 on the test split, 3 points of recall is noise, and the interval is what
stops a tuning session from chasing it.

Two retrievers are compared PAIRED, never by laying two intervals side by side.
Some questions are hard for every retriever and some are easy for every one, and
that shared difficulty makes each interval wide. On the same questions it cancels
out: take B's score minus A's for every question, then bootstrap those
differences. At n=68 two separate intervals can overlap while the paired one
sits clear of zero, which is the whole reason for pairing. Phase 4 and every
phase after it make "A vs B on the same questions" claims, so this is the only
comparison the harness prints.

A question that is in the gold set but missing from a run counts as a miss, never
as a skip. A retriever that returns nothing must score zero.

Abstention (precision and recall on the hard negatives) arrives in Phase 5, when
there is a guardrail threshold to measure.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from math import log2
from typing import NamedTuple

KS = (1, 5, 10, 20)
BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20260924
CONFIDENCE = 0.95


class Metric(NamedTuple):
    value: float
    low: float          # lower end of the 95% bootstrap interval
    high: float
    n: int              # questions the mean was taken over

    def __str__(self) -> str:
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}]"


class Paired(NamedTuple):
    a: float            # A's mean
    b: float            # B's mean
    diff: float         # B minus A, averaged over the same questions
    low: float          # lower end of the 95% paired bootstrap interval of diff
    high: float
    n: int
    better: int         # questions where B scored higher than A
    worse: int          # questions where B scored lower
    same: int

    def verdict(self, name_a: str = "A", name_b: str = "B") -> str:
        """Only an interval that excludes zero names a winner."""
        if self.low > 0:
            return f"{name_b} better"
        if self.high < 0:
            return f"{name_a} better"
        return "no clear difference"


def hit_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """1.0 when any chunk that answers the question is in the top k."""
    answers = set(relevant)
    return float(any(chunk_id in answers for chunk_id in ranked[:k]))


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str], k: int = 10) -> float:
    """1 over the rank of the first chunk that answers, 0 if none does."""
    answers = set(relevant)
    for position, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in answers:
            return 1.0 / position
    return 0.0


def ndcg(ranked: Sequence[str], relevant: Iterable[str], k: int = 10,
         answers: int | None = None) -> float:
    """Binary relevance, log2 position discount, ideal ranking capped at k.

    answers is how many DISTINCT answers the relevant chunks hold. When several
    labels print the same sentence, their chunks are one answer in many copies,
    so only the first `answers` hits earn any gain. Otherwise ten copies of one
    paragraph would outscore one answer and nine other chunks, rewarding the
    near-duplicate flooding a good retriever should avoid. Without it, every
    relevant chunk counts as a different answer.
    """
    chunks = set(relevant)
    if not chunks:
        return 0.0
    cap = min(len(chunks) if answers is None else max(1, answers), len(chunks), k)
    gain, hits = 0.0, 0
    for position, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in chunks and hits < cap:
            gain += 1.0 / log2(position + 1)
            hits += 1
    ideal = sum(1.0 / log2(position + 1) for position in range(1, cap + 1))
    return gain / ideal


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(scores: Sequence[float], rounds: int = BOOTSTRAP_ROUNDS,
                 confidence: float = CONFIDENCE,
                 seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """Percentile bootstrap over the QUESTIONS.

    Resampling the questions is the right unit: the gold set is a sample of the
    questions a user might ask, and the interval answers "how much of this score
    is the questions I happened to pick?". Seeded, so a published interval can be
    reproduced exactly.
    """
    scores = list(scores)
    if not scores:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(scores)
    means = sorted(sum(rng.choices(scores, k=n)) / n for _ in range(rounds))
    tail = (1.0 - confidence) / 2
    return means[int(tail * rounds)], means[min(rounds - 1, int((1.0 - tail) * rounds))]


def summarise(per_question: Mapping[str, float], seed: int = BOOTSTRAP_SEED) -> Metric:
    scores = list(per_question.values())
    low, high = bootstrap_ci(scores, seed=seed)
    return Metric(mean(scores), low, high, len(scores))


def per_question(run: Mapping[str, Sequence[str]], relevant: Mapping[str, Iterable[str]],
                 ks: Sequence[int] = KS,
                 answers: Mapping[str, int] | None = None) -> dict[str, dict[str, float]]:
    """metric name -> qid -> that question's score. The means in evaluate() and
    the differences in compare() are both taken from here, so the two can never
    disagree about what a question scored."""
    scores = {}
    for k in ks:
        scores[f"recall@{k}"] = {qid: hit_at_k(run.get(qid, ()), chunks, k)
                                 for qid, chunks in relevant.items()}
    scores["mrr@10"] = {qid: reciprocal_rank(run.get(qid, ()), chunks, 10)
                        for qid, chunks in relevant.items()}
    scores["ndcg@10"] = {qid: ndcg(run.get(qid, ()), chunks, 10, (answers or {}).get(qid))
                         for qid, chunks in relevant.items()}
    return scores


def evaluate(run: Mapping[str, Sequence[str]], relevant: Mapping[str, Iterable[str]],
             ks: Sequence[int] = KS, seed: int = BOOTSTRAP_SEED,
             answers: Mapping[str, int] | None = None) -> dict[str, Metric]:
    """run: qid -> the chunk ids the retriever returned, best first.
    relevant: qid -> the chunk ids that answer it.
    answers: qid -> how many distinct answers those chunks hold, for nDCG.

    Only questions present in `relevant` are scored, so negatives stay out of the
    retrieval numbers by construction rather than by remembering to exclude them.
    """
    return {name: summarise(scores, seed)
            for name, scores in per_question(run, relevant, ks, answers).items()}


def compare(run_a: Mapping[str, Sequence[str]], run_b: Mapping[str, Sequence[str]],
            relevant: Mapping[str, Iterable[str]], ks: Sequence[int] = KS,
            seed: int = BOOTSTRAP_SEED,
            answers: Mapping[str, int] | None = None) -> dict[str, Paired]:
    """B against A on the same questions, metric by metric.

    The interval is the ordinary bootstrap of the per-question differences:
    resampling a question takes its A score and its B score together, which is
    what makes it paired. Same seed as evaluate(), so a comparison can be
    reproduced exactly.
    """
    scores_a = per_question(run_a, relevant, ks, answers)
    scores_b = per_question(run_b, relevant, ks, answers)
    compared = {}
    for name, by_qid in scores_a.items():
        diffs = [scores_b[name][qid] - score for qid, score in by_qid.items()]
        low, high = bootstrap_ci(diffs, seed=seed)
        better = sum(diff > 0 for diff in diffs)
        worse = sum(diff < 0 for diff in diffs)
        compared[name] = Paired(mean(by_qid.values()), mean(scores_b[name].values()),
                                mean(diffs), low, high, len(diffs),
                                better, worse, len(diffs) - better - worse)
    return compared


def format_table(metrics: Mapping[str, Metric], title: str = "") -> str:
    lines = [title] if title else []
    lines.append(f"  {'metric':<10} {'score':>6}   {'95% interval':<16} n")
    for name, metric in metrics.items():
        lines.append(f"  {name:<10} {metric.value:>6.3f}   "
                     f"[{metric.low:.3f}, {metric.high:.3f}]   {metric.n:>3}")
    return "\n".join(lines)


def format_comparison(compared: Mapping[str, Paired], name_a: str, name_b: str) -> str:
    n = next(iter(compared.values())).n if compared else 0
    header = (f"  {'metric':<10} {'A':>6} {'B':>6} {'B-A':>7}   {'95% interval':<17}"
              f" {'B+':>3} {'B-':>3} {'=':>3}   verdict")
    lines = [f"paired: {name_b} (B) against {name_a} (A), the same {n} questions", header]
    for name, p in compared.items():
        lines.append(f"  {name:<10} {p.a:>6.3f} {p.b:>6.3f} {p.diff:>+7.3f}   "
                     f"[{p.low:+.3f}, {p.high:+.3f}]  {p.better:>3} {p.worse:>3} {p.same:>3}"
                     f"   {p.verdict(name_a, name_b)}")
    lines.append("  B+ / B- / =: questions where B scored higher, lower, the same")
    return "\n".join(lines)
