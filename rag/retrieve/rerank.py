"""Phase 5: a cross-encoder that scores how well a chunk answers a question.

Dense search compares two vectors made separately, one for the question and one
for the chunk. A cross-encoder reads the question and the chunk together, so
every question word can attend to every chunk word. That is more precise, and
much slower: nothing can be computed ahead of time.

The model is ms-marco-MiniLM-L-6-v2 from the sentence-transformers team (UKP
Lab, Germany), built on Microsoft's MiniLM, Apache 2.0, run as ONNX through
fastembed. It was trained on MS MARCO, whose terms allow research use only. It
reads what BM25 reads: drug names, section title and chunk text, cut at 512
tokens. Its score is a logit: higher means a better answer, with no fixed scale.

Measured on this CPU (Phase 5, step 3): about 100 ms per question-chunk pair,
so 50 candidates take 5 seconds. Reranking hybrid's top 50 and then collapsing
near-copies gave recall@5 0.809 against hybrid-dedup's 0.706, paired +0.103
[+0.000, +0.206], and cheaper settings gained nothing clear. So the reranker is
not in the default pipeline; rerank_trial.py reproduces that table, and step 4
tests its scores as a signal for refusing to answer.

Usage:
    from rag.retrieve.rerank import Reranker
    Reranker().rerank("Is bruxism listed for duloxetine?", chunk_ids)
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from rag.index.bm25_text import bm25_text

MODEL_ID = "Xenova/ms-marco-MiniLM-L-6-v2"
RAGDATA = Path("D:/capstone/data/rag")
CHUNKS = RAGDATA / "chunks.parquet"
MODELS = RAGDATA / "models"
BATCH = 64


def by_score(chunk_ids: Sequence[str], scores: Sequence[float]) -> list[tuple[str, float]]:
    """(chunk_id, score), best first. Ties keep the order the chunks came in, so
    a reranked list never depends on how a sort breaks ties."""
    order = sorted(range(len(chunk_ids)), key=lambda i: -scores[i])
    return [(chunk_ids[i], float(scores[i])) for i in order]


class ChunkTexts(dict):
    """chunk_id -> the text the reranker reads, fetched from chunks.parquet on
    first use and kept. One query per batch of new ids, about 0.2 s."""

    def __init__(self, chunks: Path = CHUNKS):
        super().__init__()
        self.chunks = Path(chunks)

    def fetch(self, chunk_ids: Sequence[str]) -> list[str]:
        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in self]
        if missing:
            import duckdb
            rows = duckdb.execute(
                f"SELECT chunk_id, text, generic_name, brand_name, section "
                f"FROM '{self.chunks.as_posix()}' WHERE chunk_id IN (SELECT unnest(?))",
                [missing]).fetchall()
            for chunk_id, text, generic, brand, section in rows:
                self[chunk_id] = bm25_text(text, generic, brand, section)
        return [self[chunk_id] for chunk_id in chunk_ids]


class Reranker:
    """texts maps chunk ids to what the model reads (a ChunkTexts by default);
    model is anything with fastembed's rerank(query, documents, batch_size)."""

    def __init__(self, texts: Mapping | None = None, model=None):
        self.texts = ChunkTexts() if texts is None else texts
        if model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            model = TextCrossEncoder(MODEL_ID, cache_dir=str(MODELS))
        self.model = model

    def scores(self, question: str, chunk_ids: Sequence[str]) -> list[float]:
        """One score per chunk, in the order given."""
        if not chunk_ids:
            return []
        if hasattr(self.texts, "fetch"):
            documents = self.texts.fetch(chunk_ids)
        else:
            documents = [self.texts[chunk_id] for chunk_id in chunk_ids]
        return [float(score) for score in self.model.rerank(question, documents, batch_size=BATCH)]

    def rerank(self, question: str, chunk_ids: Sequence[str]) -> list[tuple[str, float]]:
        """The chunks reordered by score, best first, as (chunk_id, score)."""
        return by_score(chunk_ids, self.scores(question, chunk_ids))
