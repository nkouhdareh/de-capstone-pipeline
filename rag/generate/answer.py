"""Phase 6: one question in, one cited answer or one refusal out.

    question
      -> guardrail        refuses here, before any model is called (Phase 5)
      -> hybrid-dedup     the top K chunks (Phase 4 and 5)
      -> prompt           numbered sources, the question repeated after them
      -> backend          any generator behind backends.Backend
      -> citation check   every sentence cited, validly, and supported

Two kinds of refusal, kept apart because they fail differently: the guardrail
refuses on what retrieval knows (an unknown word, nothing close), and costs no
generation; the model refuses, with the prompt's exact sentence, when it reads
the chunks and finds no answer in them.

K = 5: recall@5 is what the project measures, and five chunks of up to 480
tokens fit the local model's context with room for the answer.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import NamedTuple

from rag.generate.backends import Backend, Generation
from rag.generate.prompt import CitationReport, Source, build_prompt, check_citations
from rag.retrieve.guardrail import Verdict

K = 5


class Answer(NamedTuple):
    question: str
    text: str
    refused_by: str | None            # "guardrail", "model" or None
    sources: tuple[Source, ...]
    report: CitationReport | None     # None when the guardrail refused
    verdict: Verdict
    generation: Generation | None
    seconds: float


def refusal_text(verdict: Verdict) -> str:
    if verdict.unknown_words:
        return ("No label in the index contains: " + ", ".join(verdict.unknown_words)
                + ". This question cannot be answered from the indexed labels.")
    return "Nothing in the indexed labels is close enough to this question to answer it."


def idf_weight(sparse) -> Callable[[str], float]:
    """A word's weight for the citation check: its BM25 idf in the index. A word
    no chunk contains gets the highest weight there is, since it is the clearest
    sign of something the sources never said."""
    highest = float(sparse.idf.max())

    def weight(term: str) -> float:
        term_id = sparse.term_id.get(term)
        return float(sparse.idf[term_id]) if term_id is not None else highest
    return weight


class Answerer:
    """retriever has search(question, k) -> chunk ids; guardrail has
    check(question) -> Verdict; texts maps chunk ids to what the model reads
    (a ChunkTexts, or any mapping); backend is a backends.Backend; stem and
    weight are the citation check's, from the BM25 index."""

    def __init__(self, retriever, guardrail, texts, backend: Backend, k: int = K,
                 stem: Callable[[str], str] | None = None,
                 weight: Callable[[str], float] | None = None):
        self.retriever, self.guardrail, self.texts, self.backend = retriever, guardrail, texts, backend
        self.k, self.stem, self.weight = k, stem, weight

    def answer(self, question: str) -> Answer:
        started = time.perf_counter()
        verdict = self.guardrail.check(question)
        if not verdict.answer:
            return Answer(question, refusal_text(verdict), "guardrail", (), None, verdict, None,
                          time.perf_counter() - started)
        chunk_ids = self.retriever.search(question, self.k)
        if hasattr(self.texts, "fetch"):
            texts = self.texts.fetch(chunk_ids)
        else:
            texts = [self.texts[chunk_id] for chunk_id in chunk_ids]
        sources = tuple(Source(chunk_id, text) for chunk_id, text in zip(chunk_ids, texts))
        generation = self.backend.generate(*build_prompt(question, sources))
        report = check_citations(generation.text, sources, question, self.stem, self.weight)
        return Answer(question, generation.text, "model" if report.refused else None, sources, report,
                      verdict, generation, time.perf_counter() - started)
