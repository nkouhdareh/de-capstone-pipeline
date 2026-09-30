"""Phase 6: the prompt the generator reads, and a check of the citations it writes.

The prompt numbers the retrieved chunks [1] to [n], tells the model to cite
after every sentence, and gives it one exact sentence for "the sources do not
answer". The question is repeated after the sources: with about 2,000 tokens of
label text in between, a question stated only at the top is easy to lose.

The citation check is deterministic, with no second model acting as judge. For
every sentence of the answer it asks:

    cited        does the sentence cite at least one source?
    valid        is every cited number one of the sources given?
    supported    do the sentence's own words appear in the sources it cites?

"Supported" looks only at what the sentence adds: its content words, minus
stopwords, minus filler such as "label" or "states", minus the citation markers,
minus every word already in the question (a drug name or "magnesium" is in the
question and in every source, so it proves nothing). Each remaining word counts
by its weight, which the caller passes in: BM25's idf, so a rare word such as
"alopecia" counts for much more than "patients". At least MIN_SUPPORT of that
weight, stemmed on both sides, must be found in the chunks the sentence cites.
It cannot prove a claim true, but it catches the dangerous failure: a sentence
citing [1] for something [1] never says. Pure Python, so CI runs its tests.

A small model does not always refuse with the exact sentence alone: it may add
a remark before it. An answer containing the refusal sentence anywhere is a
refusal.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

from rag.index.bm25_text import TOKEN, tokenize

REFUSAL = "The retrieved label sections do not answer this question."
MIN_SUPPORT = 0.5
# Words an answer uses to talk about the sources, which the sources never say.
FILLER = frozenset({
    "label", "labels", "section", "sections", "source", "sources", "state", "states",
    "stated", "say", "says", "said", "report", "reports", "reported", "mention", "mentions",
    "mentioned", "list", "lists", "listed", "according", "also", "additionally", "yes",
    "which", "however", "may", "can", "should", "would", "could", "does", "do", "has",
    "have", "had", "from", "include", "includes", "including",
})
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

SYSTEM = (
    "You answer questions about US drug labels using only the numbered sources you are given. "
    "After every sentence, cite the sources it comes from, like [1] or [2][3]. "
    "Do not use anything you know that the sources do not say. "
    "If the sources do not contain the answer, do not explain what they do contain: "
    f"reply with exactly this one sentence and nothing else: {REFUSAL} "
    "Keep the answer to at most four sentences."
)


class Source(NamedTuple):
    chunk_id: str
    text: str           # what the model reads: drug names, section title, chunk text


def build_prompt(question: str, sources: Sequence[Source]) -> tuple[str, str]:
    """(system, user) messages. Sources are numbered from 1 in the order given."""
    blocks = "\n\n".join(f"[{number}] {source.text}" for number, source in enumerate(sources, start=1))
    user = (f"Sources:\n\n{blocks}\n\n"
            f"Question: {question}\n"
            "Answer using only the sources above, with a citation after every sentence. "
            f"If they do not contain the answer, reply only: {REFUSAL}")
    return SYSTEM, user


def cited_numbers(sentence: str) -> list[int]:
    """Every source number a sentence cites, in order: [1], [2][3] and [1, 2] all count."""
    return [int(n) for group in CITATION.findall(sentence) for n in group.split(",")]


def sentences(answer: str) -> list[str]:
    return [part.strip() for part in SENTENCE_END.split(answer.strip()) if part.strip()]


def content_words(sentence: str) -> list[str]:
    return [word for word in tokenize(CITATION.sub(" ", sentence)) if word not in FILLER]


class SentenceCheck(NamedTuple):
    sentence: str
    cited: tuple[int, ...]
    valid: bool
    support: float


class CitationReport(NamedTuple):
    refused: bool
    checks: tuple[SentenceCheck, ...]

    @property
    def uncited(self) -> int:
        return sum(not check.cited for check in self.checks)

    @property
    def invalid(self) -> int:
        return sum(bool(check.cited) and not check.valid for check in self.checks)

    @property
    def unsupported(self) -> int:
        return sum(bool(check.cited) and check.valid and check.support < MIN_SUPPORT
                   for check in self.checks)

    @property
    def ok(self) -> bool:
        return self.refused or (bool(self.checks) and not (self.uncited or self.invalid or self.unsupported))


def check_citations(answer: str, sources: Sequence[Source], question: str = "",
                    stem: Callable[[str], str] | None = None,
                    weight: Callable[[str], float] | None = None) -> CitationReport:
    """weight gives a stemmed word's importance (BM25's idf); without it every
    word counts the same."""
    if REFUSAL in answer:
        return CitationReport(True, ())
    stem = stem or (lambda word: word)
    weight = weight or (lambda word: 1.0)
    source_words = [{stem(word) for word in TOKEN.findall(source.text.lower())} for source in sources]
    asked = {stem(word) for word in TOKEN.findall(question.lower())}
    checks = []
    for sentence in sentences(answer):
        cited = tuple(cited_numbers(sentence))
        valid = all(1 <= number <= len(sources) for number in cited)
        words = [word for word in (stem(w) for w in content_words(sentence)) if word not in asked]
        support = 0.0
        if cited and valid:
            pool = set().union(*(source_words[number - 1] for number in cited))
            total = sum(weight(word) for word in words)
            # A sentence with nothing to check, such as "Yes [1].", is not held against it.
            support = sum(weight(word) for word in words if word in pool) / total if total else 1.0
        checks.append(SentenceCheck(sentence, cited, valid, support))
    return CitationReport(False, tuple(checks))
