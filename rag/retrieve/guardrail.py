"""Phase 5: decide whether to answer at all (BR-17, TR-55).

A retriever always returns something, so a system that always answers will
answer "What is the maximum dose of gliclazide?" from some other drug's label.
The guardrail refuses instead, in retrieval, before any generator sees the
chunks: prompt-based refusal is unreliable.

Two rules, either one refuses:

1. The question uses a word that no chunk in the index contains. 12 of the 15
   dev negatives ask about a drug with no label here (domperidone, gliclazide,
   metamizole), and those names are not in BM25's vocabulary at all. The
   refusal can name the word, which also helps with a misspelling.
2. The best dense cosine similarity is below MIN_COSINE: nothing in the index
   is close enough in meaning.

Chosen on dev (15 negatives, 68 answerable questions), by a rule fixed before
looking: the cosine cut is the highest that wrongly refuses at most 2 of the
68, rounded down inside the range that gives the same result (0.720 to 0.729).
Together the rules refuse 14 of 15 negatives and wrongly refuse 2 answerable
questions. The reranker's best score was tried as well and separated worse
(AUC 0.86 against cosine's 0.93) at 0.5 s a question. rag/eval/guardrail_eval.py
reproduces all of it; the test split judges it once, at the end.

Cosine comes from exact search on purpose: HNSW lost a negative entirely
(Phase 4), and a refusal rule is only as good as the score it reads.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import NamedTuple

from rag.index.bm25_text import distinct, tokenize

MIN_COSINE = 0.72


class Verdict(NamedTuple):
    answer: bool
    reason: str               # "ok", "unknown words" or "low similarity"
    unknown_words: tuple      # question words no chunk contains
    best_cosine: float


def unknown_words(words: Iterable[str], known: Callable[[str], bool]) -> tuple:
    """The words, in order and without repeats, for which known() is false."""
    return tuple(word for word in distinct(words) if not known(word))


def decide(unknown: tuple, best_cosine: float, min_cosine: float = MIN_COSINE) -> Verdict:
    if unknown:
        return Verdict(False, "unknown words", unknown, best_cosine)
    if best_cosine < min_cosine:
        return Verdict(False, "low similarity", unknown, best_cosine)
    return Verdict(True, "ok", unknown, best_cosine)


class Guardrail:
    """dense and sparse are the DenseRetriever and SparseRetriever already
    loaded for search, so the guardrail costs one extra top-1 search."""

    def __init__(self, dense, sparse, min_cosine: float = MIN_COSINE):
        self.dense, self.sparse, self.min_cosine = dense, sparse, min_cosine

    def known(self, word: str) -> bool:
        term = self.sparse.stem(word) if self.sparse.stem else word
        return term in self.sparse.term_id

    def check(self, question: str) -> Verdict:
        best = self.dense.search(question, 1)
        best_cosine = best[0][1] if best else -1.0
        return decide(unknown_words(tokenize(question), self.known), best_cosine, self.min_cosine)
