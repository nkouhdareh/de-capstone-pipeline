"""Phase 3: dense retrieval, by exact search over the arctic-embed-s index.

A question is embedded with arctic's instruction in front of it, compared with
every chunk vector, and the closest chunk ids come back, best first.

Exact search, not approximate. 360,916 vectors of 384 numbers is one matrix
product per question, about 140 million multiply-adds, which numpy does in tens
of milliseconds. At this scale exact search is fast enough to be the ground
truth, so an approximate index (HNSW, in Phase 4) gets measured against it
rather than trusted. Every vector is L2-normalised, so a dot product is the
cosine similarity.

The index's manifest records how its chunks were embedded, and the retriever
refuses an index whose model or prefixes disagree with this code: that mismatch
loses recall without raising any error.

Usage, and the retriever behind `python -m rag.eval.run_eval --retriever dense`:
    from rag.retrieve.dense import DenseRetriever
    DenseRetriever().search("Is teeth grinding listed as a side effect of duloxetine?", k=5)
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from rag.index.embedding_text import MODEL_ID, QUERY_PREFIX, query_text

INDEX = Path("D:/capstone/data/rag/index/arctic-s-fp32")


def manifest_problems(manifest: Mapping, use_prefix: bool = True) -> list[str]:
    """Every difference between how an index was built and how this code queries it."""
    problems = []
    if manifest.get("model") != MODEL_ID:
        problems.append(f"built with {manifest.get('model')!r}, queried with {MODEL_ID!r}")
    if manifest.get("passage_prefix", "") != "":
        problems.append(f"chunks embedded with prefix {manifest['passage_prefix']!r}, arctic expects none")
    if use_prefix and manifest.get("query_prefix") != QUERY_PREFIX:
        problems.append(f"index expects query prefix {manifest.get('query_prefix')!r}, "
                        f"this code adds {QUERY_PREFIX!r}")
    return problems


def top_k(scores: np.ndarray, k: int) -> np.ndarray:
    """Positions of the k highest scores, best first. argpartition finds the top k
    without sorting all 360,916 scores; only those k get sorted."""
    k = min(k, scores.shape[0])
    if k <= 0:
        return np.empty(0, dtype=np.int64)
    top = np.argpartition(-scores, k - 1)[:k]
    return top[np.argsort(-scores[top], kind="stable")]


class DenseRetriever:
    def __init__(self, index_dir: Path = INDEX, model=None, use_prefix: bool = True,
                 threads: int = 8):
        index_dir = Path(index_dir)
        self.manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        problems = manifest_problems(self.manifest, use_prefix)
        if problems:
            raise ValueError(f"{index_dir} does not match this code:\n  " + "\n  ".join(problems))
        self.vectors = np.load(index_dir / "vectors.npy")
        self.ids = (index_dir / "chunk_ids.txt").read_text(encoding="utf-8").split()
        if len(self.ids) != self.vectors.shape[0]:
            raise ValueError(f"{len(self.ids):,} chunk ids for {self.vectors.shape[0]:,} vectors")
        self.use_prefix = use_prefix
        self._row: dict[str, int] | None = None
        if model is None:
            from rag.index.build_index import load_model
            model = load_model(self.manifest["precision"], threads)
        self.model = model

    def embed_query(self, question: str) -> np.ndarray:
        text = query_text(question) if self.use_prefix else question
        return np.asarray(next(iter(self.model.embed([text]))), dtype=np.float32)

    def search(self, question: str, k: int = 20) -> list[tuple[str, float]]:
        """The k closest chunks, best first, as (chunk_id, cosine similarity)."""
        scores = self.vectors @ self.embed_query(question)
        return [(self.ids[i], float(scores[i])) for i in top_k(scores, k)]

    def __call__(self, question: Mapping, k: int) -> list[str]:
        """The retriever interface run_eval expects: a gold record in, chunk ids out."""
        return [chunk_id for chunk_id, _ in self.search(question["question"], k)]

    def vectors_of(self, chunk_ids: Sequence[str]) -> np.ndarray:
        """The stored vectors of these chunks, in the order given. The id-to-row map
        is built on first use, so a plain search never pays for it."""
        if self._row is None:
            self._row = {chunk_id: i for i, chunk_id in enumerate(self.ids)}
        return self.vectors[[self._row[chunk_id] for chunk_id in chunk_ids]]
