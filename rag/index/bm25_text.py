"""What BM25 reads, for chunks and for questions, and the BM25 formula itself.

Kept apart from sparse.py for the same reason embedding_text.py is kept apart
from dense.py: these rules must be the same on both sides, and their tests must
run in CI, where only pytest is installed. Nothing here imports numpy.

A chunk is read as its drug names, its section title and its text. Unlike the
embedding model, BM25 has no window, so nothing is ever trimmed: every brand
and generic name stays searchable.

Tokens are runs of lowercase letters and digits, so "0078-0357" becomes two
tokens and "QT-prolongation" becomes two. The 33 English stopwords are Lucene's
default set, the one Elasticsearch ships. Words are then cut to their stem with
the Snowball English stemmer, so "headaches" and "headache" meet at "headach".
Stemming is passed in rather than imported, because the stemmer is a compiled
library that CI does not have; english_stemmer() loads it where it exists.

The formula is Okapi BM25 with Lucene's idf, which never goes negative:

    idf(t)       = ln(1 + (N - df + 0.5) / (df + 0.5))
    weight(t, d) = idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avglen))

    tf      how often the term is in this chunk
    df      how many chunks hold the term at all
    k1      how fast repeats stop counting: the 10th "nausea" adds little
    b       how much a long chunk is marked down for being long

k1 = 1.2 and b = 0.75 are the textbook values and Lucene's defaults. A chunk's
score for a question is the sum of weight(t, d) over the question's distinct
terms.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from math import log

from rag.index.embedding_text import drug_names, section_title

TEXT_VERSION = "bm25-v1"
K1 = 1.2
B = 0.75

TOKEN = re.compile(r"[a-z0-9]+")
# Lucene's EnglishAnalyzer stop set, as shipped by Elasticsearch.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", "in", "into",
    "is", "it", "no", "not", "of", "on", "or", "such", "that", "the", "their", "then",
    "there", "these", "they", "this", "to", "was", "will", "with",
})

Stemmer = Callable[[str], str]


def bm25_text(text: str, generic: str | None, brand: str | None, section: str) -> str:
    """The chunk as BM25 reads it: names, section title, text. Never trimmed."""
    return f"{drug_names(generic, brand)}\n{section_title(section)}\n{text}"


def tokenize(text: str, stem: Stemmer | None = None) -> list[str]:
    tokens = [token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS]
    return [stem(token) for token in tokens] if stem else tokens


def english_stemmer() -> Stemmer:
    """Snowball English, from py-rust-stemmers (Qdrant, MIT), which fastembed
    already installs. Imported here, not at the top, so CI never needs it."""
    from py_rust_stemmers import SnowballStemmer
    return SnowballStemmer("english").stem_word


def idf(df: int, n_docs: int) -> float:
    return log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def term_weight(tf: float, doc_len: float, avg_len: float, idf_value: float,
                k1: float = K1, b: float = B) -> float:
    return idf_value * tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))


def score_all(query: Sequence[str], docs: Sequence[Sequence[str]],
              k1: float = K1, b: float = B) -> list[float]:
    """Every document's BM25 score for one query, in plain Python. Too slow for
    360,916 chunks; it exists as the reference the fast index is tested against.
    query and docs are already tokenized."""
    n_docs = len(docs)
    if not n_docs:
        return []
    counts = [Counter(doc) for doc in docs]
    avg_len = sum(len(doc) for doc in docs) / n_docs or 1.0
    df = Counter(term for count in counts for term in count)
    scores = []
    for doc, count in zip(docs, counts):
        scores.append(sum(term_weight(count[term], len(doc), avg_len, idf(df[term], n_docs), k1, b)
                          for term in set(query) if count[term]))
    return scores


def distinct(tokens: Iterable[str]) -> list[str]:
    """A question's distinct terms, in first-seen order. Repeating a word in a
    question does not make it count twice."""
    return list(dict.fromkeys(tokens))
